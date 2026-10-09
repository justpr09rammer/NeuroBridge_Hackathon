"""Application services: the only layer that touches both the database and the engine.
Used by the Streamlit UI, the FastAPI API, the seed script and the evaluation lab."""
from __future__ import annotations

import json
import shutil
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from talentlens import config
from talentlens.core import taxonomy as tx
from talentlens.core.documents import DocumentError, ExtractedDocument, extract_pdf
from talentlens.core.interview import generate_questions
from talentlens.core.matching import analyse_cv
from talentlens.core.models import (
    AppSetting, Assessment, Candidate, CandidateReport, CVDocument, EvaluationRun, LearningResource,
    RecruiterReview, Requirement, RequirementAssessment, Vacancy,
)
from talentlens.core.profile import extract_profile
from talentlens.core.reports import build_report
from talentlens.core.requirements import RequirementSpec, extract_requirements, normalize_weights, review_wording
from talentlens.core.retrieval import ResourceIndex, check_url
from talentlens.core.scoring import DEFAULT_POLICY, compute_score, rank
from talentlens.core.security import detect_injection, redact_pii

# ---------------------------------------------------------------------------
# Settings
DEFAULT_SETTINGS = {
    "mode": "demo",            # demo | live
    "llm_consent": False,      # explicit consent before CV text leaves the machine
    "blind_mode": False,
    "policy": dict(DEFAULT_POLICY),
}


def get_setting(s: Session, key: str) -> Any:
    row = s.get(AppSetting, key)
    return row.value.get("v") if row else DEFAULT_SETTINGS.get(key)


def set_setting(s: Session, key: str, value: Any) -> None:
    row = s.get(AppSetting, key)
    if row is None:
        s.add(AppSetting(key=key, value={"v": value}))
    else:
        row.value = {"v": value}


def live_mode_active(s: Session) -> bool:
    return get_setting(s, "mode") == "live" and config.anthropic_key_present()


def pipeline_label(s: Session) -> str:
    if live_mode_active(s):
        return f"Live AI Mode ({config.ANTHROPIC_MODEL})"
    return "Demo Mode (local analysis, no LLM)"


def _provider():
    from talentlens.core.llm import AnthropicProvider
    return AnthropicProvider()


# ---------------------------------------------------------------------------
# Resources
def seed_resources(s: Session) -> int:
    data = json.loads((config.DATA_DIR / "resources.json").read_text())
    existing = {u for (u,) in s.execute(select(LearningResource.url))}
    added = 0
    for r in data:
        if r["url"] in existing:
            continue
        s.add(LearningResource(estimated_time="Not stated (self-paced)", verification_status="seed entry (not checked at runtime)", **r))
        added += 1
    return added


def resource_dicts(s: Session) -> list[dict]:
    rows = s.scalars(select(LearningResource).order_by(LearningResource.skill, LearningResource.title)).all()
    return [{"id": r.id, "title": r.title, "provider": r.provider, "topic": r.topic, "skill": r.skill, "description": r.description,
             "url": r.url, "difficulty": r.difficulty, "estimated_time": r.estimated_time,
             "verification_status": r.verification_status, "last_checked": r.last_checked} for r in rows]


def resource_index(s: Session) -> ResourceIndex:
    return ResourceIndex(resource_dicts(s))


def verify_resource_links(s: Session) -> list[dict]:
    out = []
    for r in s.scalars(select(LearningResource)).all():
        status, when = check_url(r.url)
        r.verification_status, r.last_checked = status, when
        out.append({"title": r.title, "url": r.url, "status": status})
    return out


# ---------------------------------------------------------------------------
# Vacancies
def analyze_job_description(s: Session, text: str, title: str = "") -> tuple[list[RequirementSpec], list[dict], str, str]:
    """Returns (specs, wording_flags, source, error_message)."""
    err = ""
    specs: list[RequirementSpec] = []
    source = "local"
    if live_mode_active(s):
        try:
            from talentlens.core.llm import extract_requirements_llm
            specs = extract_requirements_llm(_provider(), text)
            source = f"llm:{config.ANTHROPIC_MODEL}"
        except Exception as e:  # graceful fallback
            err = f"Live extraction failed ({e}); used local parser instead."
    if not specs:
        specs = extract_requirements(text)
    return specs, review_wording(text, specs, title), source, err


def create_vacancy(s: Session, fields: dict, specs: list[RequirementSpec | dict], flags: list[dict] | None = None,
                   source: str = "local", is_demo: bool = False, demo_key: str | None = None) -> Vacancy:
    v = Vacancy(**{k: fields.get(k, "") for k in ("title", "company", "department", "location", "employment_type",
                                                    "salary_range", "description", "recruiter_notes")},
                wording_flags=flags or [], extraction_source=source, is_demo=is_demo, demo_key=demo_key)
    if not v.title:
        raise ValueError("Job title is required.")
    s.add(v)
    s.flush()
    _set_requirements(s, v, [x.to_dict() if isinstance(x, RequirementSpec) else x for x in specs])
    return v


def _clean_req(d: dict, pos: int) -> dict:
    cat = d.get("category") if d.get("category") in tx.CATEGORIES else tx.OTHER
    prio = d.get("priority") if d.get("priority") in ("must", "nice") else "must"
    syn = d.get("synonyms") or []
    if isinstance(syn, str):
        syn = [x.strip() for x in syn.split(",") if x.strip()]
    params = dict(d.get("params") or {})
    if cat == tx.SOFT:
        params["interview_only"] = True
    name = str(d.get("name") or "").strip()
    if not name:
        raise ValueError("Every requirement needs a name.")
    key = str(d.get("key") or "").strip() or tx.slugify(name)
    weight = 0.0 if cat == tx.SOFT else max(0.0, float(d.get("weight") or 0))
    return dict(key=key, name=name[:200], category=cat, priority=prio, weight=weight, position=pos,
                description=str(d.get("description") or "")[:500], guidance=str(d.get("guidance") or "")[:500],
                synonyms=syn[:15], params=params)


def _set_requirements(s: Session, v: Vacancy, rows: list[dict]) -> None:
    existing = {r.id: r for r in v.requirements}
    keep: set[int] = set()
    seen_keys: set[str] = set()
    for pos, d in enumerate(rows):
        clean = _clean_req(d, pos)
        if clean["key"] in seen_keys:
            clean["key"] = f"{clean['key']}_{pos}"
        seen_keys.add(clean["key"])
        rid = d.get("id")
        if rid and int(rid) in existing:
            req = existing[int(rid)]
            for k, val in clean.items():
                setattr(req, k, val)
            keep.add(req.id)
        else:
            v.requirements.append(Requirement(**clean))
    for rid, req in existing.items():
        if rid not in keep:
            v.requirements.remove(req)
    s.flush()


def update_vacancy(s: Session, v: Vacancy, fields: dict, rows: list[dict] | None = None, reassess: bool = True) -> Vacancy:
    for k in ("title", "company", "department", "location", "employment_type", "salary_range", "description", "recruiter_notes"):
        if k in fields:
            setattr(v, k, fields[k] or "")
    if rows is not None:
        _set_requirements(s, v, rows)
        v.wording_flags = review_wording(v.description, [RequirementSpec(**{k: r.get(k) for k in ("key", "name", "category", "priority", "weight", "description", "guidance", "synonyms", "params")}) for r in [requirement_dict(x) for x in v.requirements]], v.title)
        if reassess:
            for c in v.candidates:
                assess_candidate(s, c)
    return v


def requirement_dict(r: Requirement) -> dict:
    return {"id": r.id, "key": r.key, "name": r.name, "category": r.category, "priority": r.priority, "weight": r.weight,
            "description": r.description, "guidance": r.guidance, "synonyms": list(r.synonyms or []), "params": dict(r.params or {})}


def normalize_vacancy_weights(s: Session, v: Vacancy) -> None:
    scored = [r for r in v.requirements if r.category != tx.SOFT]
    for r, w in zip(scored, normalize_weights([r.weight for r in scored])):
        r.weight = w


# ---------------------------------------------------------------------------
# Candidates
def _store_file(vacancy_id: int, filename: str, data: bytes) -> Path:
    folder = config.UPLOAD_DIR / f"vacancy_{vacancy_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex[:10]}_{filename}"
    path.write_bytes(data)
    return path


def ingest_cv(s: Session, v: Vacancy, filename: str, data: bytes, is_synthetic: bool = False, assess: bool = True) -> tuple[Candidate | None, str]:
    """Validate, extract, store and (optionally) assess one PDF. Returns (candidate, message)."""
    try:
        doc = extract_pdf(filename, data)
    except DocumentError as e:
        return None, f"{filename}: rejected. {e}"
    dup = s.scalar(select(Candidate).where(Candidate.vacancy_id == v.id, Candidate.content_hash == doc.content_hash))
    if dup is not None:
        return dup, f"{doc.filename}: duplicate of {dup.display_id}; not added again."
    cand = _create_candidate(s, v, doc, is_synthetic)
    path = _store_file(v.id, doc.filename, data)
    cand.documents[0].stored_path = str(path)
    if assess:
        assess_candidate(s, cand)
    msg = f"{doc.filename}: processed as {cand.display_id}."
    if doc.readability != "ok":
        msg += " Flagged for manual inspection: " + " ".join(doc.warnings)
    elif doc.hidden_text:
        msg += " Hidden text found and excluded from evidence."
    return cand, msg


def ingest_document(s: Session, v: Vacancy, doc: ExtractedDocument, is_synthetic: bool = True, assess: bool = True) -> Candidate:
    """Ingest an already-extracted document (evaluation and tests)."""
    cand = _create_candidate(s, v, doc, is_synthetic)
    if assess:
        assess_candidate(s, cand)
    return cand


def _create_candidate(s: Session, v: Vacancy, doc: ExtractedDocument, is_synthetic: bool) -> Candidate:
    profile = extract_profile(doc.pages)
    cand = Candidate(display_id="pending", name=profile["name"], email=profile["email"], phone=profile["phone"],
                     content_hash=doc.content_hash, profile=profile, is_synthetic=is_synthetic)
    cand.documents.append(CVDocument(filename=doc.filename, size_bytes=doc.size_bytes, page_count=doc.page_count, text=doc.text,
                                     pages=doc.pages, hidden_text=doc.hidden_text, readability=doc.readability,
                                     processing_error="; ".join(doc.warnings)))
    v.candidates.append(cand)  # keeps the in-session collection consistent
    s.flush()
    cand.display_id = f"CAND-{cand.id:04d}"
    return cand


def reprocess_document(s: Session, cand: Candidate) -> str:
    d = cand.documents[0] if cand.documents else None
    if d is None or not d.stored_path or not Path(d.stored_path).exists():
        return "Original file is not available; re-assessed from stored text."
    doc = extract_pdf(d.filename, Path(d.stored_path).read_bytes())
    d.text, d.pages, d.hidden_text, d.readability = doc.text, doc.pages, doc.hidden_text, doc.readability
    d.processing_error = "; ".join(doc.warnings)
    cand.profile = extract_profile(doc.pages)
    assess_candidate(s, cand)
    return "Document re-extracted and re-assessed."


def _page_of(quote: str, pages: list[str]) -> int | None:
    from talentlens.core.security import normalize_for_quote
    q = normalize_for_quote(quote)
    for i, p in enumerate(pages, start=1):
        if q and q in normalize_for_quote(p):
            return i
    return None


def assess_candidate(s: Session, cand: Candidate, today: date | None = None, force_local: bool = False) -> Assessment:
    v = cand.vacancy if cand.vacancy is not None else s.get(Vacancy, cand.vacancy_id)
    doc = cand.documents[0]
    reqs = [requirement_dict(r) for r in v.requirements]
    blind = bool(get_setting(s, "blind_mode"))
    t0 = time.perf_counter()
    analysis = analyse_cv(doc.pages, reqs, today=today)  # always computed: flags + fallback
    items, pipeline = analysis.items, config.LOCAL_PIPELINE_NAME
    if not force_local and live_mode_active(s) and get_setting(s, "llm_consent"):
        try:
            from talentlens.core.llm import assess_cv_llm
            # Identifiers are always stripped from contact data; names too in blind mode.
            text = redact_pii(doc.text, cand.name if blind else "", cand.display_id)
            items = assess_cv_llm(_provider(), text, reqs)
            for it in items:
                it.page = _page_of(it.evidence, doc.pages) if it.evidence else None
            pipeline = f"llm:{config.ANTHROPIC_MODEL}"
        except Exception as e:
            pipeline = f"{config.LOCAL_PIPELINE_NAME} (LLM fallback: {str(e)[:80]})"
    flags = list(analysis.flags)
    if doc.readability != "ok":
        flags.append({"type": f"document_{doc.readability}", "severity": "review", "page": None, "text": "",
                      "detail": doc.processing_error or "Document needs manual inspection."})
    if doc.hidden_text:
        flags.append({"type": "hidden_text", "severity": "review", "page": doc.hidden_text[0]["page"],
                      "text": doc.hidden_text[0]["text"][:200],
                      "detail": f"{len(doc.hidden_text)} hidden text fragment(s) (white/microscopic). Excluded from evidence."})
    req_by_key = {r.key: r for r in v.requirements}
    sr = compute_score([(req_by_key[it.requirement_key], it.status) for it in items], policy=get_setting(s, "policy"), security_flags=flags)
    a = Assessment(candidate_id=cand.id, vacancy_id=v.id, pipeline=pipeline, score=sr.score, category_scores=sr.category_scores,
                   needs_review=sr.needs_review, review_reasons=sr.review_reasons, security_flags=flags,
                   duration_ms=round((time.perf_counter() - t0) * 1000, 1), blind_mode=blind)
    for it in items:
        a.items.append(RequirementAssessment(requirement_id=req_by_key[it.requirement_key].id, status=it.status, original_status=it.status,
                                             evidence=it.evidence, page=it.page, explanation=it.explanation,
                                             matched_terms=it.matched_terms, uncertainty=it.uncertainty, follow_up=it.follow_up))
    cand.assessments.append(a)
    cand.status = "needs_review" if sr.needs_review else "assessed"
    s.flush()
    return a


def assessment_items(a: Assessment) -> list[dict]:
    out = []
    for ra in a.items:
        r = ra.requirement
        out.append({"ra_id": ra.id, "key": r.key, "name": r.name, "category": r.category, "priority": r.priority, "weight": r.weight,
                    "params": r.params or {}, "status": ra.status, "original_status": ra.original_status, "evidence": ra.evidence,
                    "page": ra.page, "explanation": ra.explanation, "uncertainty": ra.uncertainty, "follow_up": ra.follow_up,
                    "matched_terms": ra.matched_terms, "corrected": ra.corrected})
    order = {c: i for i, c in enumerate(tx.CATEGORIES)}
    out.sort(key=lambda i: (order.get(i["category"], 99), i["priority"] != "must"))
    return out


def score_assessment(s: Session, a: Assessment, weights: dict[str, float] | None = None):
    items = assessment_items(a)
    return compute_score([(i, i["status"]) for i in items], weights=weights, policy=get_setting(s, "policy"), security_flags=a.security_flags)


def display_label(c: Candidate, blind: bool) -> str:
    if blind or not c.name:
        return c.display_id
    return f"{c.name} ({c.display_id})"


def latest_decision(c: Candidate) -> str | None:
    for r in reversed(c.reviews):
        if r.kind == "decision":
            return r.decision
    return None


def manual_flag(c: Candidate) -> bool:
    for r in reversed(c.reviews):
        if r.kind == "flag":
            return bool(r.payload.get("on"))
    return False


def candidate_rows(s: Session, v: Vacancy, weights: dict[str, float] | None = None, blind: bool = False) -> list[dict]:
    rows = []
    for c in v.candidates:
        a = c.latest_assessment
        if a is None:
            continue
        sr = score_assessment(s, a, weights)
        decision = latest_decision(c)
        flagged = manual_flag(c)
        row = {"candidate_id": c.id, "display_id": c.display_id, "name": "Hidden (blind mode)" if blind else (c.name or "Not detected"),
               "score": sr.score, "demonstrated": sr.counts[tx.DEMONSTRATED], "unclear": sr.counts[tx.UNCLEAR],
               "not_found": sr.counts[tx.NOT_FOUND], "needs_review": sr.needs_review or flagged,
               "must_unverified": sum(1 for r in sr.review_reasons if r.startswith("Must-have")),
               "must_have_status": "Verified" if not any("Must-have" in r for r in sr.review_reasons) else "Needs verification",
               "flags": len([f for f in a.security_flags if f.get("severity") == "review"]),
               "screening_status": decision or ("needs review" if (sr.needs_review or flagged) else "assessed"),
               "pipeline": a.pipeline, "synthetic": c.is_synthetic}
        for cat in tx.SCORED_CATEGORIES:
            row[cat] = sr.category_scores.get(cat)
        rows.append(row)
    ranked = rank(rows)
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    return ranked


def apply_correction(s: Session, ra: RequirementAssessment, new_status: str, note: str, author: str = "Recruiter") -> None:
    if new_status not in tx.STATUSES:
        raise ValueError("Invalid status")
    old = ra.status
    ra.status, ra.corrected = new_status, new_status != ra.original_status
    a = ra.assessment
    a.candidate.reviews.append(RecruiterReview(kind="correction", note=note,
                                              payload={"requirement": ra.requirement.name, "from": old, "to": new_status}, author=author))
    s.flush()
    sr = score_assessment(s, a)
    a.score, a.category_scores, a.needs_review, a.review_reasons = sr.score, sr.category_scores, sr.needs_review, sr.review_reasons


def record_decision(s: Session, c: Candidate, decision: str, note: str = "", author: str = "Recruiter") -> None:
    if decision not in ("advance", "hold", "rejected"):
        raise ValueError("Invalid decision")
    c.reviews.append(RecruiterReview(kind="decision", decision=decision, note=note, author=author))
    c.status = decision


def add_note(s: Session, c: Candidate, note: str, author: str = "Recruiter") -> None:
    if note.strip():
        c.reviews.append(RecruiterReview(kind="note", note=note.strip()[:2000], author=author))


def set_review_flag(s: Session, c: Candidate, on: bool, note: str = "") -> None:
    c.reviews.append(RecruiterReview(kind="flag", note=note, payload={"on": on}))


def generate_report(s: Session, c: Candidate) -> CandidateReport:
    a = c.latest_assessment
    if a is None:
        raise ValueError("Candidate has not been assessed.")
    blind = bool(get_setting(s, "blind_mode"))
    idx = resource_index(s)
    res = build_report(display_label(c, blind), c.vacancy.title, assessment_items(a), idx, decision=latest_decision(c))
    rep = CandidateReport(candidate_id=c.id, markdown=res.markdown, resource_urls=res.resource_urls, source=config.LOCAL_PIPELINE_NAME)
    c.reports.append(rep)
    s.flush()
    return rep


def interview_questions(s: Session, c: Candidate) -> tuple[list[dict], str]:
    a = c.latest_assessment
    if a is None:
        return [], "not assessed"
    items = assessment_items(a)
    if live_mode_active(s) and get_setting(s, "llm_consent"):
        try:
            from talentlens.core.llm import interview_questions_llm
            slim = [{k: i[k] for k in ("name", "category", "priority", "status", "evidence")} for i in items]
            return interview_questions_llm(_provider(), slim), f"llm:{config.ANTHROPIC_MODEL}"
        except Exception as e:
            return generate_questions(items), f"local templates (LLM fallback: {str(e)[:60]})"
    return generate_questions(items), "local templates"


def delete_candidate(s: Session, c: Candidate) -> None:
    for d in c.documents:
        if d.stored_path:
            Path(d.stored_path).unlink(missing_ok=True)
    s.delete(c)


def delete_vacancy(s: Session, v: Vacancy) -> None:
    for c in v.candidates:
        for d in c.documents:
            if d.stored_path:
                Path(d.stored_path).unlink(missing_ok=True)
    folder = config.UPLOAD_DIR / f"vacancy_{v.id}"
    s.delete(v)
    s.flush()
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------------------
def dashboard_stats(s: Session) -> dict:
    vac = s.scalar(select(func.count(Vacancy.id))) or 0
    cands = s.scalar(select(func.count(Candidate.id))) or 0
    assessed_ids = s.scalars(select(Assessment.candidate_id).distinct()).all()
    latest = []
    for c in s.scalars(select(Candidate)).all():
        if c.latest_assessment:
            latest.append((c, c.latest_assessment))
    durations = [a.duration_ms for _, a in latest if a.duration_ms]
    return {
        "vacancies": vac, "candidates": cands, "assessed": len(set(assessed_ids)),
        "needs_review": sum(1 for c, a in latest if a.needs_review or manual_flag(c)),
        "avg_ms": round(sum(durations) / len(durations), 1) if durations else None,
        "scores": [a.score for _, a in latest],
        "statuses": {st: sum(1 for _, a in latest for it in a.items if it.status == st) for st in tx.STATUSES},
        "evaluations": s.scalar(select(func.count(EvaluationRun.id))) or 0,
    }


# ---------------------------------------------------------------------------
# Notifications
def candidate_email(s: Session, c: Candidate):
    """Email for the candidate's recorded decision (None for 'hold' or no decision)."""
    from talentlens.core.notifications import build_email
    a = c.latest_assessment
    decision = latest_decision(c)
    if a is None or decision not in ("advance", "rejected"):
        return None
    v = c.vacancy
    return build_email(c.name, v.title, v.company, assessment_items(a), decision, resource_index(s))


def bulk_decide(s: Session, v: Vacancy, top_n: int) -> dict:
    """Recruiter-triggered bulk decision: top N -> advance; the rest -> rejected, except
    candidates with an unclear must-have or a document flag, who are put on hold for review.
    Candidates that already have a recorded decision are left unchanged."""
    from talentlens.core.notifications import needs_human_check
    out = {"advance": 0, "rejected": 0, "hold": 0, "unchanged": 0}
    for row in candidate_rows(s, v):
        c = s.get(Candidate, row["candidate_id"])
        if latest_decision(c):
            out["unchanged"] += 1
            continue
        a = c.latest_assessment
        if row["rank"] <= top_n:
            decision = "advance"
        elif needs_human_check(assessment_items(a), a.security_flags):
            decision = "hold"
        else:
            decision = "rejected"
        record_decision(s, c, decision, f"Bulk decision: shortlist top {top_n}")
        out[decision] += 1
    return out


def email_sent(c: Candidate) -> bool:
    for r in reversed(c.reviews):
        if r.kind == "decision":
            return False
        if r.kind == "email_sent":
            return True
    return False


def mark_email_sent(s: Session, c: Candidate, subject: str) -> None:
    c.reviews.append(RecruiterReview(kind="email_sent", note=subject, payload={"simulated": True}))


def clear_decisions(s: Session, v: Vacancy) -> None:
    for c in v.candidates:
        for r in [r for r in c.reviews if r.kind in ("decision", "email_sent")]:
            c.reviews.remove(r)
        c.status = "needs_review" if c.latest_assessment and c.latest_assessment.needs_review else "assessed"
