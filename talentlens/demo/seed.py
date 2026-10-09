"""Idempotent demo seeding and reset."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from talentlens import config
from talentlens.core import services
from talentlens.core.documents import render_pdf
from talentlens.core.evaluation import local_assessor, run_evaluation
from talentlens.core.models import EvaluationCase, EvaluationRun, Vacancy
from talentlens.core.requirements import extract_requirements, review_wording
from talentlens.demo.demo_data import DEMO_CVS, DEMO_VACANCY


def demo_pdf_bytes() -> list[tuple[str, bytes]]:
    """Render the fictional demo CVs as real PDFs (also written to var/demo_cvs for upload demos)."""
    config.ensure_dirs()
    out = []
    for n, cv in enumerate(DEMO_CVS, start=1):
        data = render_pdf(cv["lines"], cv.get("hidden"))
        fname = f"{n:02d}_{cv['key']}_FICTIONAL.pdf"
        (config.DEMO_PDF_DIR / fname).write_bytes(data)
        out.append((fname, data))
    return out


def seed_demo(s: Session) -> dict:
    added_res = services.seed_resources(s)
    s.flush()
    v = s.scalar(select(Vacancy).where(Vacancy.demo_key == DEMO_VACANCY["demo_key"]))
    created = False
    msgs: list[str] = []
    if v is None:
        specs = extract_requirements(DEMO_VACANCY["description"])
        flags = review_wording(DEMO_VACANCY["description"], specs, DEMO_VACANCY["title"])
        v = services.create_vacancy(s, DEMO_VACANCY, specs, flags, source="local", is_demo=True, demo_key=DEMO_VACANCY["demo_key"])
        created = True
    if not v.candidates:
        for fname, data in demo_pdf_bytes():
            _, msg = services.ingest_cv(s, v, fname, data, is_synthetic=True)
            msgs.append(msg)
    return {"resources_added": added_res, "vacancy_created": created, "vacancy_id": v.id, "messages": msgs}


def reset_demo(s: Session) -> dict:
    for v in s.scalars(select(Vacancy).where(Vacancy.is_demo.is_(True))).all():
        services.delete_vacancy(s, v)
    for run in s.scalars(select(EvaluationRun)).all():
        s.delete(run)
    s.flush()
    s.expunge_all()  # SQLite may reuse primary keys; start from a clean identity map
    return seed_demo(s)


def run_and_store_evaluation(s: Session, use_llm: bool = False) -> EvaluationRun:
    resources = services.resource_dicts(s)
    if use_llm:
        from talentlens.core.llm import assess_cv_llm, extract_requirements_llm
        provider = services._provider()
        res = run_evaluation(resources, assessor=lambda t, r: assess_cv_llm(provider, t, r), pipeline=provider.name,
                             extractor=lambda jd: extract_requirements_llm(provider, jd))
    else:
        res = run_evaluation(resources, assessor=local_assessor)
    run = EvaluationRun(pipeline=res.pipeline, metrics=res.metrics, duration_s=res.duration_s,
                        config={"dataset": "12 hand-labelled demo CVs + 24 generator-labelled CVs + 4 labelled JDs",
                                "reference_date": "2026-10-09", "llm": use_llm})
    for c in res.cases:
        run.cases.append(EvaluationCase(**c))
    s.add(run)
    s.flush()
    return run
