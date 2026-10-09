"""Candidate notification emails.

* Rejection: explains *why*, grouped by requirement category, and links only to
  verified resources from the curated library (RAG), plus a practical next step.
* Invitation: names the matched strengths and the topics the interview will cover.
Emails are only produced for decisions a recruiter has recorded.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from talentlens.core import taxonomy as tx
from talentlens.core.reports import EXERCISES, _project_idea
from talentlens.core.retrieval import ResourceIndex
from talentlens.core.security import strip_unknown_urls


@dataclass
class Email:
    kind: str  # rejection | invitation
    subject: str
    body: str
    resources: list[dict] = field(default_factory=list)


def _candidate_reason(item: dict) -> str:
    text = (item.get("uncertainty") or item["explanation"]) if item["status"] == tx.UNCLEAR else item["explanation"]
    return text.replace("the CV", "your CV").replace("The CV", "Your CV")


def build_email(name: str, vacancy_title: str, company: str, items: list[dict], decision: str,
                index: ResourceIndex) -> Email | None:
    company = company or "our company"
    greeting = f"Dear {name.split()[0]}," if name else "Dear candidate,"
    scored = [i for i in items if i["category"] != tx.SOFT]
    strengths = [i for i in scored if i["status"] == tx.DEMONSTRATED]

    if decision == "advance":
        topics = [i for i in items if i["status"] != tx.DEMONSTRATED or i["category"] == tx.SOFT][:4]
        lines = [greeting, "",
                 f"Thank you for applying for the {vacancy_title} role at {company}. We are pleased to invite you to an interview.", ""]
        if strengths:
            lines += ["What stood out in your CV:"] + [f"  - {i['name']}" for i in strengths[:5]] + [""]
        if topics:
            lines += ["In the interview we would like to talk about:"] + [f"  - {i['name']}" for i in topics] + [""]
        lines += ["Please reply with two or three time slots that suit you in the coming week.", "",
                  "Kind regards,", f"{company} Recruitment Team"]
        return Email("invitation", f"Interview invitation: {vacancy_title}", "\n".join(lines))

    if decision != "rejected":
        return None

    gaps = sorted([i for i in scored if i["status"] != tx.DEMONSTRATED],
                  key=lambda i: (i["priority"] != "must", i["status"] != tx.NOT_FOUND))
    lines = [greeting, "",
             f"Thank you for applying for the {vacancy_title} role at {company}. After carefully reviewing your application, "
             "we have decided not to move forward with it for this position.", "",
             "Why: we compared your CV with each requirement of the role.", ""]
    if strengths:
        lines += ["What your CV showed clearly:"] + [f"  ✓ {i['name']}" for i in strengths] + [""]
    if gaps:
        lines += ["What we could not confirm from your CV:"]
        for cat in tx.SCORED_CATEGORIES:
            in_cat = [g for g in gaps if g["category"] == cat]
            if not in_cat:
                continue
            lines.append(f"  {cat}")
            for g in in_cat:
                need = "required" if g["priority"] == "must" else "nice to have"
                lines.append(f"    - {g['name']} ({need}): {_candidate_reason(g)}")
        lines += ["", "If you do have these skills, describe them in your CV with a concrete example "
                  "(what you built, the tools you used, the result). Absence from a CV is not proof that a skill is missing.", ""]

    resources: list[dict] = []
    seen: set[str] = set()
    plan: list[str] = []
    for g in gaps[:4]:
        hits = index.search(g["key"], g["name"], k=1)
        if hits and hits[0].resource["url"] not in seen:
            r = hits[0].resource
            seen.add(r["url"])
            resources.append({"skill": g["name"], "title": r["title"], "provider": r["provider"], "url": r["url"]})
            practice = EXERCISES.get(g["key"], "")
            plan.append(f"  - {g['name']}: {r['title']} ({r['provider']}) {r['url']}" + (f"\n      Practice: {practice}" if practice else ""))
    if plan:
        lines += ["How to strengthen your next application (free, verified resources):"] + plan + [""]
    if gaps:
        project = _project_idea([g["key"] for g in gaps], [i["key"] for i in items if i["category"] == tx.TECHNICAL])
        lines += ["Suggested practice project:", "  " + project.replace("**", ""), ""]
    lines += ["We genuinely appreciate the time you invested and would welcome a future application.", "",
              "Kind regards,", f"{company} Recruitment Team", "",
              "This feedback was prepared with AI assistance from your CV and the job requirements, and approved by a recruiter. "
              "It is not a judgement of your ability."]
    body, _ = strip_unknown_urls("\n".join(lines), {r["url"] for r in index.resources})
    return Email("rejection", f"Your application for {vacancy_title}", body, resources)


def needs_human_check(items: list[dict], security_flags: list[dict]) -> bool:
    """True when a decision should not be made in bulk: an unclear must-have
    (the candidate may well have it) or a document flag (injection, hidden text, unreadable)."""
    unclear_must = any(i["priority"] == "must" and i["status"] == tx.UNCLEAR and i["category"] != tx.SOFT for i in items)
    return unclear_must or any(f.get("severity") == "review" for f in security_flags)
