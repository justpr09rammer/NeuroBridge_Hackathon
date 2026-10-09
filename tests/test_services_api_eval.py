from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from talentlens.core import db, services
from talentlens.core import taxonomy as tx
from talentlens.core.documents import render_pdf
from talentlens.core.models import Candidate, LearningResource, Vacancy
from talentlens.demo.demo_data import DEMO_CVS
from talentlens.demo.seed import reset_demo, run_and_store_evaluation, seed_demo


def test_seed_is_idempotent_and_persistent(tmp_db):
    with db.session_scope() as s:
        seed_demo(s)
    with db.session_scope() as s:
        out = seed_demo(s)
        assert not out["vacancy_created"] and out["resources_added"] == 0
    db.configure(tmp_db)  # simulate an application restart
    with db.session_scope() as s:
        assert s.scalar(select(func.count(Candidate.id))) == len(DEMO_CVS)
        assert s.scalar(select(func.count(Vacancy.id))) == 1
        assert s.scalar(select(func.count(LearningResource.id))) > 20


def test_demo_flags_and_review(tmp_db):
    with db.session_scope() as s:
        seed_demo(s)
        v = s.scalar(select(Vacancy))
        by_name = {c.name: c for c in v.candidates}
        inj = by_name["Lala Huseynova"].latest_assessment
        assert any(f["type"] == "instruction_like_text" for f in inj.security_flags) and inj.needs_review
        stuffed = by_name["Orkhan Ismayilov"].latest_assessment
        assert {"hidden_text", "possible_keyword_stuffing"} <= {f["type"] for f in stuffed.security_flags}
        rashad = by_name["Rashad Valiyev"].latest_assessment
        assert rashad.needs_review and rashad.score >= 90
        rows = services.candidate_rows(s, v)
        assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))


def test_duplicate_upload_correction_decision_delete(tmp_db):
    with db.session_scope() as s:
        seed_demo(s)
        v = s.scalar(select(Vacancy))
        data = render_pdf(DEMO_CVS[0]["lines"])
        c1, _ = services.ingest_cv(s, v, "dup.pdf", data)
        c2, msg = services.ingest_cv(s, v, "dup2.pdf", data)
        assert c1.id == c2.id and "duplicate" in msg
        a = c1.latest_assessment
        ra = next(x for x in a.items if x.status == tx.DEMONSTRATED)
        before = a.score
        services.apply_correction(s, ra, tx.NOT_FOUND, "checked by phone")
        assert a.score < before and ra.corrected and ra.original_status == tx.DEMONSTRATED
        services.record_decision(s, c1, "rejected", "test")
        rep = services.generate_report(s, c1)
        assert "not be moving forward" in rep.markdown
        path = Path(c1.documents[0].stored_path)
        assert path.exists()
        services.delete_candidate(s, c1)
    assert not path.exists()


def test_blind_mode_and_llm_quote_validation(tmp_db, monkeypatch):
    """Live AI Mode with a fake provider: names are removed from the prompt in blind mode,
    and a fabricated quotation is discarded and downgraded."""
    captured = {}

    class FakeProvider:
        name = "llm:fake"

        def complete_json(self, system, user, max_tokens=4000):
            captured["user"] = user
            return {"items": [{"requirement_key": "python", "status": "DEMONSTRATED", "evidence": "Invented quote that is not in the CV"},
                              {"requirement_key": "sql", "status": "DEMONSTRATED", "evidence": "Designed PostgreSQL schemas and optimised slow SQL queries (p95 from 900 ms to 120 ms)"}]}

    with db.session_scope() as s:
        seed_demo(s)
        services.set_setting(s, "mode", "live")
        services.set_setting(s, "llm_consent", True)
        services.set_setting(s, "blind_mode", True)
    monkeypatch.setattr(services, "live_mode_active", lambda s: True)
    monkeypatch.setattr(services, "_provider", lambda: FakeProvider())
    with db.session_scope() as s:
        c = s.scalar(select(Candidate).where(Candidate.name == "Aysel Hasanova"))
        a = services.assess_candidate(s, c)
        items = {i["key"]: i for i in services.assessment_items(a)}
        assert a.pipeline == "llm:" + services.config.ANTHROPIC_MODEL
        assert items["python"]["status"] == tx.UNCLEAR and items["python"]["evidence"] == ""
        assert items["sql"]["status"] == tx.DEMONSTRATED and items["sql"]["page"] == 1
        assert items["git"]["status"] == tx.UNCLEAR  # missing model output is never a silent pass
    assert "Aysel" not in captured["user"] and "aysel.hasanova@example.com" not in captured["user"]


def test_llm_failure_falls_back_to_local(tmp_db, monkeypatch):
    class Broken:
        name = "llm:broken"

        def complete_json(self, *a, **k):
            raise RuntimeError("boom")

    with db.session_scope() as s:
        seed_demo(s)
        services.set_setting(s, "llm_consent", True)
    monkeypatch.setattr(services, "live_mode_active", lambda s: True)
    monkeypatch.setattr(services, "_provider", lambda: Broken())
    with db.session_scope() as s:
        c = s.scalar(select(Candidate))
        a = services.assess_candidate(s, c)
        assert a.pipeline.startswith("local-rules-v1 (LLM fallback")
        specs, _, source, err = services.analyze_job_description(s, "Requirements:\n- Python", "Dev")
        assert source == "local" and err and specs


def test_evaluation_metrics_are_computed(tmp_db):
    with db.session_scope() as s:
        seed_demo(s)
        run = run_and_store_evaluation(s)
        m = run.metrics
        assert all(0.0 <= x["value"] <= 1.0 and x["n"] > 0 for x in m.values())
        assert m["E_name_invariance"]["value"] == 1.0 and m["E_name_invariance"]["n"] >= 100
        assert m["F_injection"]["value"] == 1.0
        assert m["G_provenance"]["value"] == 1.0
        assert m["B_quote_validity"]["value"] == 1.0
        assert len(run.cases) > 50
        reset_demo(s)


@pytest.fixture()
def client(tmp_db):
    from api.main import app
    with db.session_scope() as s:
        seed_demo(s)
    with TestClient(app) as c:
        yield c


def test_api_endpoints(client):
    assert client.get("/health").json()["status"] == "ok"
    vacs = client.get("/vacancies").json()
    vid = vacs[0]["id"]
    assert client.get(f"/vacancies/{vid}").status_code == 200
    assert client.get("/vacancies/999").status_code == 404
    created = client.post("/vacancies", json={"title": "Data Analyst", "description": "Requirements:\n- SQL\n- Python with pandas"})
    assert created.status_code == 201 and {r["key"] for r in created.json()["requirements"]} >= {"sql", "python", "data_analysis"}
    nid = created.json()["id"]
    upd = client.put(f"/vacancies/{nid}", json={"title": "Data Analyst II", "requirements": [{"name": "SQL", "key": "sql", "weight": 20}]})
    assert upd.json()["title"] == "Data Analyst II" and len(upd.json()["requirements"]) == 1
    assert client.post("/vacancies", json={"title": ""}).status_code == 422
    files = [("files", ("a.pdf", render_pdf(DEMO_CVS[1]["lines"]), "application/pdf")), ("files", ("b.txt", b"hello", "text/plain"))]
    up = client.post(f"/vacancies/{nid}/candidates/upload", files=files).json()["results"]
    assert up[0]["accepted"] and not up[1]["accepted"]
    cands = client.get(f"/vacancies/{nid}/candidates", params={"blind": True}).json()
    assert cands and cands[0]["name"] == "Hidden (blind mode)"
    cid = cands[0]["candidate_id"]
    assert client.get(f"/candidates/{cid}").json()["assessment"]["items"]
    assert client.post(f"/candidates/{cid}/assess").json()["pipeline"] == "local-rules-v1"
    assert "Development report" in client.get(f"/candidates/{cid}/report").json()["markdown"]
    assert client.get("/candidates/12345").status_code == 404
    res = client.get("/resources/search", params={"skill": "docker"}).json()
    assert res["results"][0]["url"].startswith("https://docs.docker.com")
    ev = client.post("/evaluations/run").json()
    assert ev["total_cases"] > 50 and "E_name_invariance" in ev["metrics"]


def test_bulk_decisions_and_emails(tmp_db):
    with db.session_scope() as s:
        seed_demo(s)
        v = s.scalar(select(Vacancy))
        out = services.bulk_decide(s, v, 4)
        assert out["advance"] == 4 and out["rejected"] > 0 and out["hold"] > 0
        by = {c.name: c for c in v.candidates}
        # prompt-injection CV is never bulk-rejected: it waits for a person
        assert services.latest_decision(by["Lala Huseynova"]) == "hold"
        assert services.candidate_email(s, by["Lala Huseynova"]) is None
        rej = services.candidate_email(s, by["Nigar Guliyeva"])
        assert rej.kind == "rejection" and "SQL (required)" in rej.body and "What your CV showed clearly" in rej.body
        allowed = {r["url"] for r in services.resource_dicts(s)}
        assert rej.resources and all(r["url"] in allowed for r in rej.resources)
        assert "postgresql.org" in rej.body
        inv = services.candidate_email(s, by["Aysel Hasanova"])
        assert inv.kind == "invitation" and "interview" in inv.body.lower()
        services.mark_email_sent(s, by["Nigar Guliyeva"], rej.subject)
        assert services.email_sent(by["Nigar Guliyeva"])
        assert services.bulk_decide(s, v, 4)["unchanged"] == len(v.candidates)  # decisions are never overwritten
        services.clear_decisions(s, v)
        assert all(services.latest_decision(c) is None for c in v.candidates)
