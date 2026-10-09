"""Candidate development reports (local template engine + RAG resources).

Reports separate *missing CV evidence* from an *actual skill gap* and only ever
link to resources retrieved from the curated library.
"""
from __future__ import annotations

from dataclasses import dataclass

from talentlens.core import taxonomy as tx
from talentlens.core.retrieval import ResourceIndex
from talentlens.core.security import strip_unknown_urls

EXERCISES = {
    "python": "Solve 5 small problems a day (string parsing, dictionaries, file I/O) and add unit tests.",
    "sql": "Write 20 queries on a sample dataset: joins, GROUP BY, window functions; explain one query plan.",
    "databases": "Design a schema for a small booking system, then add constraints and indexes and justify them.",
    "git": "Use feature branches and pull requests for your own project; practise resolving a merge conflict.",
    "java": "Implement a small domain model (orders, items) with tests; use collections and streams.",
    "spring_boot": "Build a CRUD REST service with validation and a PostgreSQL repository.",
    "rest_api": "Design and document 5 endpoints with correct methods and status codes (OpenAPI).",
    "docker": "Containerise one of your projects and run it with its database via docker-compose.",
    "kubernetes": "Deploy a containerised app to a local cluster (kind/minikube) and scale it.",
    "aws": "Complete a free cloud fundamentals module and deploy a static site or small API.",
    "testing": "Add unit tests to an existing project until the core logic is covered; include edge cases.",
    "linux": "Do your daily development from the terminal for a week: navigation, grep, pipes, scripts.",
    "machine_learning": "Train and evaluate a baseline classifier on a public dataset; report precision/recall.",
    "data_analysis": "Analyse a public dataset with pandas and write up three findings with charts.",
    "messaging": "Build a producer/consumer pair that processes events and handles retries.",
    "ci_cd": "Add a pipeline that runs tests and linting on every push.",
    "lang_english": "Write a weekly technical summary in English and practise explaining your project aloud.",
}

PROJECT_TEMPLATES = [
    ({"spring_boot", "java"}, "Task-tracker REST API in Java/Spring Boot"),
    ({"python", "rest_api", "sql", "databases"}, "Library-loans REST API in Python with a relational database"),
    ({"data_analysis", "machine_learning"}, "Public-data analysis notebook with a simple predictive model"),
    ({"javascript", "react"}, "Expense-tracker web app with a React front end"),
    ({"docker", "kubernetes", "ci_cd", "aws"}, "Deployment pipeline for a small web service"),
]

DISCLAIMER = ("This report is an AI-assisted development guide generated from the CV and the vacancy requirements. "
              "It is not a judgement of ability: a requirement marked 'not found in CV' means the CV did not show it, "
              "not that the skill is missing.")


@dataclass
class ReportResult:
    markdown: str
    resource_urls: list[str]
    removed_urls: list[str]


def _project_idea(gap_keys: list[str], vacancy_keys: list[str]) -> str:
    wanted = set(gap_keys) | set(vacancy_keys)
    best, best_overlap = None, 0
    for keys, title in PROJECT_TEMPLATES:
        ov = len(keys & wanted)
        if ov > best_overlap:
            best, best_overlap = title, ov
    title = best or "A small end-to-end application relevant to the role"
    tech = [tx.SKILL_BY_KEY[k].name for k in gap_keys if k in tx.SKILL_BY_KEY][:4]
    tech_txt = f" Make sure it uses {', '.join(tech)}." if tech else ""
    return (f"**{title}.** Keep the scope small: 3–5 features, a README explaining design decisions, automated tests, "
            f"and a public repository you can link from your CV.{tech_txt}")


def build_report(
    candidate_label: str,
    vacancy_title: str,
    items: list[dict],
    index: ResourceIndex,
    decision: str | None = None,
    allowed_urls: set[str] | None = None,
) -> ReportResult:
    """items: dicts with key, name, category, priority, status, evidence, explanation."""
    scored = [i for i in items if i["category"] != tx.SOFT]
    strengths = [i for i in scored if i["status"] == tx.DEMONSTRATED]
    unclear = [i for i in scored if i["status"] == tx.UNCLEAR]
    missing = [i for i in scored if i["status"] == tx.NOT_FOUND]
    soft = [i for i in items if i["category"] == tx.SOFT]
    gaps = sorted(missing + unclear, key=lambda i: (i["priority"] != "must", i["status"] != tx.NOT_FOUND))

    L: list[str] = [f"# Development report: {vacancy_title}", f"**Candidate:** {candidate_label}", ""]
    if decision == "rejected":
        L += ["Thank you for applying. After review, the hiring team will not be moving forward with your application for this role. "
              "We prepared this guide so the time you invested is useful for your next step.", ""]
    else:
        L += ["_This guide does not represent a hiring decision._", ""]

    L += ["## 1. Summary",
          f"Your CV shows clear evidence for **{len(strengths)}** of {len(scored)} scored requirements, "
          f"limited evidence for **{len(unclear)}**, and no evidence for **{len(missing)}**.", ""]

    L += ["## 2. Demonstrated strengths"]
    L += [f"- **{i['name']}**: \"{i['evidence'][:160]}\"" for i in strengths] or ["- No requirement was clearly demonstrated in the CV."]
    L += [""]

    L += ["## 3. Requirements with limited evidence"]
    L += [f"- **{i['name']}** ({'must-have' if i['priority'] == 'must' else 'nice-to-have'}): {i['explanation']}" for i in unclear] or ["- None."]
    L += [""]

    L += ["## 4. Requirements not found in your CV"]
    L += [f"- **{i['name']}** ({'must-have' if i['priority'] == 'must' else 'nice-to-have'}): {i['explanation']}" for i in missing] or ["- None."]
    L += [""]

    L += ["## 5. Missing evidence vs. a real skill gap",
          "If you *do* have one of the skills above, the fastest improvement is to describe it in your CV with a concrete example "
          "(what you built, which tools you used, the result). If you don't have it yet, the plan below suggests how to build it.", ""]

    L += ["## 6. Skills to develop"]
    L += [f"{n}. {g['name']}" for n, g in enumerate(gaps[:5], start=1)] or ["Your CV covers the scored requirements. Focus on depth and interview preparation."]
    L += [""]

    gap_keys = [g["key"] for g in gaps]
    vac_keys = [i["key"] for i in items if i["category"] == tx.TECHNICAL]
    L += ["## 7. Portfolio project", _project_idea(gap_keys, vac_keys), ""]

    # Retrieval: resources only from the curated library
    retrieved: dict[str, list] = {}
    for g in gaps[:5]:
        hits = index.search(g["key"], g["name"], k=2)
        retrieved[g["key"]] = hits

    L += ["## 8. Four-week example plan"]
    focus = gaps[:3]
    for w in range(3):
        if w < len(focus):
            g = focus[w]
            hits = retrieved.get(g["key"], [])
            res = f" Start with *{hits[0].resource['title']}*." if hits else ""
            L.append(f"- **Week {w + 1}: {g['name']}.**{res} {EXERCISES.get(g['key'], 'Practise with a small, concrete exercise and write down what you learned.')}")
        else:
            L.append(f"- **Week {w + 1}:** Deepen your strongest skills; add tests and documentation to your project.")
    L.append("- **Week 4:** Finish the portfolio project, update your CV with concrete examples, and rehearse the interview topics below.")
    L += [""]

    L += ["## 9. Verified learning resources"]
    urls: list[str] = []
    any_hit = False
    for g in gaps[:5]:
        hits = retrieved.get(g["key"], [])
        if not hits:
            L.append(f"- **{g['name']}**: no matching resource in the verified library yet.")
            continue
        for h in hits:
            any_hit = True
            r = h.resource
            urls.append(r["url"])
            L.append(f"- **{g['name']}**: [{r['title']}]({r['url']}) by {r['provider']} ({r['difficulty']}). _Why: {h.reason}_")
    if not gaps:
        L.append("- No gaps detected; no resources needed.")
    elif not any_hit:
        L.append("- The verified library has no resources for these topics yet.")
    L += [""]

    L += ["## 10. Practice and interview preparation"]
    L += [f"- Prepare a 2-minute example that shows your {s['name'].lower()} (situation, action, result)." for s in soft[:3]]
    L += [f"- Be ready to explain this CV line in depth: \"{i['evidence'][:120]}\"" for i in strengths[:2]]
    if len(L) and L[-1] == "## 10. Practice and interview preparation":
        L.append("- Practise explaining one project end to end in under three minutes.")
    L += ["", "## 11. About this report", DISCLAIMER]

    md = "\n".join(L)
    allowed = allowed_urls if allowed_urls is not None else {r["url"] for r in index.resources}
    md, removed = strip_unknown_urls(md, allowed)
    return ReportResult(md, sorted(set(urls)), removed)
