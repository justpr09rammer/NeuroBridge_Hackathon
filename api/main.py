"""TalentLens AI REST API (FastAPI). Shares the same services layer as the Streamlit app.

Run: uvicorn api.main:app --reload --port 8000   (docs at /docs)
No authentication is implemented: this is a local hackathon MVP.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from talentlens import config
from talentlens.core import db, services
from talentlens.core import taxonomy as tx
from talentlens.core.models import Candidate, Vacancy

@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.get_engine()  # configure on first use; tests may have configured a temporary database already
    yield


app = FastAPI(title="TalentLens AI API", version="1.0.0", lifespan=lifespan,
              description="Evidence-based CV screening. Local hackathon MVP; not production-ready for real hiring decisions.")


@app.exception_handler(ValueError)
async def _value_error(_, exc: ValueError):
    return JSONResponse(status_code=422, content={"error": "validation_error", "detail": str(exc)})


class RequirementIn(BaseModel):
    id: int | None = None
    key: str | None = None
    name: str = Field(min_length=1, max_length=200)
    category: str = tx.TECHNICAL
    priority: Literal["must", "nice"] = "must"
    weight: float = Field(default=10, ge=0, le=1000)
    description: str = ""
    guidance: str = ""
    synonyms: list[str] = []
    params: dict = {}


class VacancyIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str = ""
    department: str = ""
    location: str = ""
    employment_type: str = "Full-time"
    salary_range: str = ""
    description: str = Field(default="", max_length=20000)
    recruiter_notes: str = ""
    requirements: list[RequirementIn] | None = None  # None -> extract from description


def _vacancy_out(v: Vacancy) -> dict:
    return {"id": v.id, "title": v.title, "company": v.company, "department": v.department, "location": v.location,
            "employment_type": v.employment_type, "description": v.description, "extraction_source": v.extraction_source,
            "wording_flags": v.wording_flags, "candidate_count": len(v.candidates),
            "requirements": [services.requirement_dict(r) for r in v.requirements]}


def _get_vacancy(s, vid: int) -> Vacancy:
    v = s.get(Vacancy, vid)
    if v is None:
        raise HTTPException(404, detail=f"Vacancy {vid} not found")
    return v


def _get_candidate(s, cid: int) -> Candidate:
    c = s.get(Candidate, cid)
    if c is None:
        raise HTTPException(404, detail=f"Candidate {cid} not found")
    return c


@app.get("/health")
def health() -> dict:
    with db.session_scope() as s:
        return {"status": "ok", "mode": services.pipeline_label(s)}


@app.get("/vacancies")
def list_vacancies() -> list[dict]:
    with db.session_scope() as s:
        from sqlalchemy import select
        return [_vacancy_out(v) for v in s.scalars(select(Vacancy).order_by(Vacancy.id)).all()]


@app.post("/vacancies", status_code=201)
def create_vacancy(body: VacancyIn) -> dict:
    with db.session_scope() as s:
        if body.requirements is None:
            specs, flags, source, _err = services.analyze_job_description(s, body.description, body.title)
            rows = [x.to_dict() for x in specs]
        else:
            rows, source = [r.model_dump() for r in body.requirements], "manual"
            flags = []
        v = services.create_vacancy(s, body.model_dump(exclude={"requirements"}), rows, flags, source=source)
        if not flags:
            v.wording_flags = services.review_wording(v.description, None, v.title) if v.description else []
        return _vacancy_out(v)


@app.get("/vacancies/{vacancy_id}")
def get_vacancy(vacancy_id: int) -> dict:
    with db.session_scope() as s:
        return _vacancy_out(_get_vacancy(s, vacancy_id))


@app.put("/vacancies/{vacancy_id}")
def update_vacancy(vacancy_id: int, body: VacancyIn) -> dict:
    with db.session_scope() as s:
        v = _get_vacancy(s, vacancy_id)
        rows = [r.model_dump() for r in body.requirements] if body.requirements is not None else None
        services.update_vacancy(s, v, body.model_dump(exclude={"requirements"}), rows)
        return _vacancy_out(v)


@app.post("/vacancies/{vacancy_id}/candidates/upload")
async def upload_cvs(vacancy_id: int, files: list[UploadFile] = File(...)) -> dict:
    if len(files) > config.MAX_FILES_PER_BATCH:
        raise HTTPException(413, detail=f"At most {config.MAX_FILES_PER_BATCH} files per batch")
    results = []
    with db.session_scope() as s:
        v = _get_vacancy(s, vacancy_id)
        for f in files:
            data = await f.read(config.MAX_UPLOAD_BYTES + 1)
            cand, msg = services.ingest_cv(s, v, f.filename or "upload.pdf", data)
            results.append({"filename": f.filename, "candidate_id": cand.id if cand else None, "message": msg, "accepted": cand is not None})
    return {"results": results}


@app.get("/vacancies/{vacancy_id}/candidates")
def list_candidates(vacancy_id: int, blind: bool = Query(False)) -> list[dict]:
    with db.session_scope() as s:
        v = _get_vacancy(s, vacancy_id)
        return services.candidate_rows(s, v, blind=blind)


@app.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: int, blind: bool = Query(False)) -> dict:
    with db.session_scope() as s:
        c = _get_candidate(s, candidate_id)
        a = c.latest_assessment
        return {"id": c.id, "display_id": c.display_id, "name": None if blind else c.name, "vacancy_id": c.vacancy_id,
                "status": c.status, "synthetic": c.is_synthetic,
                "assessment": None if a is None else {
                    "pipeline": a.pipeline, "score": a.score, "category_scores": a.category_scores, "needs_review": a.needs_review,
                    "review_reasons": a.review_reasons, "security_flags": a.security_flags, "items": services.assessment_items(a)}}


@app.post("/candidates/{candidate_id}/assess")
def assess(candidate_id: int) -> dict:
    with db.session_scope() as s:
        c = _get_candidate(s, candidate_id)
        a = services.assess_candidate(s, c)
        return {"candidate_id": c.id, "pipeline": a.pipeline, "score": a.score, "needs_review": a.needs_review,
                "review_reasons": a.review_reasons}


@app.get("/candidates/{candidate_id}/report")
def report(candidate_id: int) -> dict:
    with db.session_scope() as s:
        c = _get_candidate(s, candidate_id)
        rep = services.generate_report(s, c)
        return {"candidate_id": c.id, "markdown": rep.markdown, "resource_urls": rep.resource_urls, "source": rep.source}


@app.post("/evaluations/run")
def run_evaluation() -> dict:
    from talentlens.demo.seed import run_and_store_evaluation
    with db.session_scope() as s:
        run = run_and_store_evaluation(s)
        return {"run_id": run.id, "pipeline": run.pipeline, "duration_s": run.duration_s, "metrics": run.metrics,
                "failed_cases": sum(1 for c in run.cases if not c.passed), "total_cases": len(run.cases)}


@app.get("/resources/search")
def search_resources(skill: str = Query(..., min_length=1, max_length=80), k: int = Query(3, ge=1, le=10)) -> dict:
    with db.session_scope() as s:
        idx = services.resource_index(s)
        key = tx.slugify(skill)
        name = tx.SKILL_BY_KEY[key].name if key in tx.SKILL_BY_KEY else skill
        hits = idx.search(key, name, k=k)
        return {"query": skill, "results": [{"title": h.resource["title"], "url": h.resource["url"], "provider": h.resource["provider"],
                                             "score": h.score, "reason": h.reason} for h in hits],
                "note": None if hits else "No relevant resource in the curated library."}
