# TalentLens AI

**Hiring that explains itself.** Evidence-based CV screening for recruiters, plus respectful development reports for candidates.

> Hackathon MVP. It supports recruiters; it does not replace them, does not eliminate bias, and is **not production-ready for real hiring decisions**. All demo people and companies are fictional.

## The problem

1. Recruiters screen hundreds of CVs per vacancy, by hand or with keyword filters, and cannot explain their decisions.
2. Candidates get silence or a generic rejection, with no idea which skills were missing.

## What TalentLens does

| Step | What happens |
|---|---|
| Vacancy | Job description → editable, categorised checklist (Technical, Experience, Education, Languages, Certifications, Other, Soft skills). Each requirement has must/nice, weight, guidance and synonyms. Wording-review suggestions flag vague, age-, gender- or origin-related phrasing. |
| Upload | Batch PDF upload with validation, duplicate detection, hidden-text detection and readability checks. |
| Matching | For each requirement: **Demonstrated / Unclear / Not found in CV**, with an **exact quotation** and page number. Keywords in a skills list or "familiar with…" are only *Unclear*. |
| Scoring | Deterministic Python: `score = 100 × Σ(weight × value) / Σ(weight)` (1 / 0.5 / 0 by default, configurable). Weights can be changed live. |
| Review | Any unverified must-have, or suspicious document content, sends the candidate to **human review**. Nobody is ever auto-rejected. |
| Decisions & emails | The recruiter shortlists the top N. Everyone else gets an answer: rejection emails explain **why**, grouped by category, and include free verified resources and a practice project. Shortlisted candidates get an interview invitation. Unclear must-haves or suspicious documents are put on hold for a person, never bulk-rejected. Sending is simulated. |
| Candidates | Development report: strengths, "missing CV evidence vs real gap", portfolio project, four-week plan, and links **only** from the curated library (RAG). |
| Interviews | 5–8 job-related questions targeting unclear evidence and claimed skills. |
| Trust | Blind screening, prompt-injection resistance, and a Quality & Fairness Lab that runs real tests. |

### Two operating modes

- **Demo Mode (default):** fully local, no API key, no internet needed. Rule-based requirement parser with synonym dictionaries, evidence extraction, TF-IDF retrieval, template-based reports and questions. Outputs are labelled `local-rules-v1`.
- **Live AI Mode (optional):** set `ANTHROPIC_API_KEY`, switch the mode in **Settings**, and tick the consent box. Claude is used for requirement extraction, semantic CV assessment and interview questions. Every response is schema-validated. Any quotation not found verbatim in the CV is discarded and the item is downgraded to *Unclear*. On any failure the app falls back to local processing. The LLM never computes scores. Outputs are labelled `llm:<model>`.

## Quick start (macOS / Linux)

```bash
./setup.sh      # creates .venv, installs requirements, initialises the DB, loads demo data, runs the evaluation once
./run.sh        # Streamlit app at http://localhost:8501
./run.sh api    # same, plus the REST API at http://localhost:8000/docs
```

Manual equivalent:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional; nothing in it is required
python -m scripts.seed          # initialise DB + fictional demo data (idempotent); add --evaluate or --reset
streamlit run app.py
```

The database is created automatically on first launch, and the demo scenario is loaded if the database is empty.

### Environment variables (all optional)

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Enables Live AI Mode | unset → Demo Mode |
| `ANTHROPIC_MODEL` | Model for Live AI Mode | `claude-sonnet-5-5` |
| `TALENTLENS_VAR_DIR` | Location of SQLite DB and uploaded PDFs | `./var` |
| `TALENTLENS_MAX_UPLOAD_MB` | Max size per PDF | `5` |

## Tests

```bash
python -m pytest -q
```

The 36 tests cover bulk decisions and notification emails, requirement extraction, weight normalisation, scoring formula, zero weights, stable ranking, must-have review, quote validation, synonyms, ambiguous evidence, prompt injection (visible and hidden text), PDF errors, retrieval provenance, reports, interview questions, blind mode (including names stripped from LLM prompts), LLM fabricated-quote rejection and fallback (with a fake provider), persistence across restarts, idempotent seeding, evaluation metrics and every API endpoint. Tests use temporary databases and never touch `var/`. No test needs an API key or internet.

## Quality & Fairness Lab

Run it from the app (**Quality & Fairness Lab → Run evaluation**), `python -m scripts.seed --evaluate`, or `POST /evaluations/run`. All metrics are computed from pipeline outputs at run time.

| Metric | Data |
|---|---|
| Requirement extraction recall / precision / category+priority accuracy | 4 labelled job descriptions (41 requirements) |
| Quotation validity, supported-claim rate | all assessed CVs |
| Precision@5 / @10 | 12 hand-labelled + 24 generator-labelled CVs, with the best achievable value shown |
| 3-class agreement, false-positive and false-negative rates | per dataset |
| Name-invariance pass rate | 144 name swaps across 24 CVs |
| Prompt-injection pass rate | 24 visible injections + 3 hidden white-text PDFs |
| Resource provenance | every URL in generated reports + a fabricated-link test |
| Document robustness, weight-change consistency, mandatory-uncertainty review | deterministic checks |

**Reading the numbers honestly.** On the latest local run, hand-labelled agreement is 98.5% (130/132). The two disagreements are kept visible as failure examples:

- "deployed with GitHub Actions" was counted as Git evidence; the label said *Unclear*.
- "Clinic appointment API: FastAPI…" was not recognised as REST API evidence.

Generator-labelled CVs reach 100% because their labels come from the same writing patterns the rules expect. They test consistency and are **optimistic**. The job descriptions were also written by the team. Treat everything as a smoke test on small synthetic data, not a benchmark.

Compared with plain keyword filtering, which treats any listed keyword as a match, TalentLens reports listed-only and keyword-stuffed skills as *Unclear*, so stuffed CVs do not rise to the top. In the demo, the keyword-stuffed CV scores 37.5, against 95.8 for real evidence.

## Architecture

```
app.py                     Streamlit entry point (Dashboard, 4 workflow steps, Quality Lab, Settings)
api/main.py                FastAPI REST API (same services layer)
talentlens/
  config.py                env-based configuration (no secrets in code)
  core/
    models.py, db.py       SQLAlchemy models (Vacancy, Requirement, Candidate, CVDocument, Assessment,
                           RequirementAssessment, RecruiterReview, CandidateReport, LearningResource,
                           EvaluationRun, EvaluationCase, AppSetting) and safe schema init
    documents.py           PDF validation, visible-text extraction, hidden-text detection (PyMuPDF)
    taxonomy.py            skills, synonyms, categories, section headers
    requirements.py        JD → requirements, wording review, weight normalisation
    matching.py            evidence engine (Demonstrated / Unclear / Not found + quotations)
    scoring.py             deterministic scoring and ranking
    security.py            injection detection, quote validation, PII redaction, URL allow-listing
    retrieval.py           TF-IDF RAG over the curated library, link checking
    reports.py, interview.py   development reports and interview questions
    notifications.py       invitation and rejection emails (reasons by category + verified resources)
    llm.py                 optional Anthropic provider with schema validation and fallback
    evaluation.py          Quality & Fairness Lab
    services.py            orchestration used by UI, API, seed script and tests
  demo/                    fictional demo vacancy, 12 CVs with hand labels, generator for 24 more
  data/resources.json      curated learning resources (real, stable URLs)
  ui/                      components, selectors and one module per page
scripts/seed.py            DB init + demo seeding (idempotent), --reset, --evaluate
tests/                     pytest suite
```

### REST API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | status and active mode |
| GET / POST | `/vacancies` | list / create (requirements are extracted if not supplied) |
| GET / PUT | `/vacancies/{id}` | read / update (re-assesses candidates) |
| POST | `/vacancies/{id}/candidates/upload` | multipart batch PDF upload |
| GET | `/vacancies/{id}/candidates?blind=true` | ranked candidates |
| GET | `/candidates/{id}` | candidate and evidence |
| POST | `/candidates/{id}/assess` | re-run assessment |
| GET | `/candidates/{id}/report` | generate a development report |
| POST | `/evaluations/run` | run and store the evaluation |
| GET | `/resources/search?skill=sql` | curated-library retrieval |

## Three-minute demo script

The app follows four steps in the sidebar: **1 · Vacancy → 2 · Screening → 3 · Candidate → 4 · Decisions & Emails**, plus the **Quality Lab**.

1. **Vacancy** (30 s): choose *Edit: Software Engineer*. The ad becomes a categorised checklist, and "young and dynamic team" is flagged.
2. **Screening** (40 s): 12 CVs ranked with evidence. Raise the Docker weight and the ranking updates instantly.
3. **Candidate** (40 s): *Rashad Valiyev* scores high, but his English level is unclear, so he goes to human review. *Lala Huseynova*'s CV tells the AI to rank her first; it is flagged and ignored. Interview questions and the full report are at the bottom of the page.
4. **Decisions & Emails** (50 s): shortlist the top 4 and click *Apply decisions*. Open a rejection email: what matched, what was missing by category, free resources, a practice project. Then click *Send all*.
5. **Quality Lab** (20 s): *Run evaluation*, and show the results and the failed cases.

## Privacy and security

- Local by default: SQLite in `var/`, PDFs in `var/uploads/`. Nothing leaves the machine unless Live AI Mode is enabled **and** consent is given. Even then, email, phone and profile links are removed (and names too in blind mode).
- CVs are untrusted data. Instruction-like text and invisible text are flagged, excluded from evidence, and cannot change scores. Nothing in an upload is executed.
- File type, header, size, emptiness, password protection and corrupt-file checks run on upload. Error messages never include secrets.
- Candidates and their stored files can be deleted from the candidate page. Demo data can be reset, with confirmation, from Settings.
- **Not implemented:** authentication, authorisation and audit-grade logging. "Reveal identity" is a UI control, not a security boundary.

## Known limitations

- The local matcher is rule-based. It can miss evidence written in unexpected ways (see the failure examples above), and it doesn't do OCR on scanned PDFs (these are flagged as unreadable).
- Blind screening removes direct identifiers only. Proxies such as university names or career gaps remain.
- Recruiter status corrections apply to the current assessment. Re-running an assessment starts fresh, but the corrections stay in the review log.
- Learning-resource URLs are seed data. They show as verified only after **Check all links now** succeeds. Estimated learning times are not invented, so they show "Not stated".
- Live AI Mode was tested with a fake provider in the test suite. It was not exercised against the real API during development (no key was available).
- Requirement extraction targets English job descriptions. Azerbaijani and Russian text is not parsed by the local rules.
- Data volumes are hackathon-sized (SQLite, single user).

## Troubleshooting

- **Port in use:** `streamlit run app.py --server.port 8502`.
- **Want a clean slate:** use Settings → *Reset demo data*, or `python -m scripts.seed --reset`, or delete `var/`.
- **Live AI Mode not activating:** check that `ANTHROPIC_API_KEY` is in `.env`, restart, select Live mode and tick consent in Settings. The sidebar shows the active mode.
- **PDF rejected:** only text-based PDFs under the size limit are accepted. Scanned images are flagged as unreadable.

## Disclosure (for judges)

- **Built** during the hackathon on 9 Oct 2026.
- **Libraries:** Streamlit, Plotly, pandas, SQLAlchemy, PyMuPDF, scikit-learn, FastAPI, Uvicorn, Pydantic, Anthropic SDK, python-dotenv, pytest.
- **Models:** none are needed for Demo Mode. Live AI Mode uses Anthropic Claude (configurable).
- **Data:** all CVs, people and companies are fictional and were written for this project. Learning resources link to public official documentation and free courses.
