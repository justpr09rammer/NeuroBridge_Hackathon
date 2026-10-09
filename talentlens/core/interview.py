"""Job-related interview question generation (local template-based fallback).

Questions only reference requirements and the candidate's own CV evidence. They
never touch protected characteristics, family status, age, health or religion.
"""
from __future__ import annotations

from talentlens.core import taxonomy as tx

PRACTICAL = {
    "python": ("Write a function that returns the three most frequent words in a text file. How would you test it?", "Clean, idiomatic Python; edge cases (empty file, ties); a unit test."),
    "sql": ("Given tables orders(id, customer_id, total, created_at) and customers(id, name), write a query for the top 5 customers by revenue last month.", "Correct JOIN, GROUP BY, date filter, ORDER BY/LIMIT; awareness of indexes."),
    "databases": ("How would you design tables for a library system with books, members and loans?", "Keys, relationships, constraints and normalisation trade-offs."),
    "git": ("You and a colleague changed the same function on different branches. Walk us through resolving it.", "Branching, merge vs rebase, conflict resolution, pull-request review."),
    "java": ("Explain how you would model an order with line items in Java and keep it immutable.", "Classes/records, encapsulation, collections, equals/hashCode."),
    "spring_boot": ("Sketch a Spring Boot endpoint that creates a customer and validates the input.", "Controller/service/repository layers, validation, error handling."),
    "rest_api": ("Design REST endpoints for creating, listing and cancelling bookings.", "Resource naming, HTTP methods, status codes, pagination, idempotency."),
    "docker": ("How would you containerise a small web service and its database for local development?", "Dockerfile basics, image layers, docker-compose, environment config."),
    "testing": ("What would you unit-test in a function that calculates a discount?", "Boundary cases, test isolation, meaningful assertions."),
}

SOFT_QUESTIONS = {
    "soft_communication": "Tell us about a time you explained a technical issue to a non-technical person. What did you do to make it clear?",
    "soft_teamwork": "Describe a disagreement within a team about a technical approach. How was it resolved?",
    "soft_problem_solving": "Describe a difficult bug you investigated. How did you narrow it down?",
    "soft_leadership": "Tell us about a time you took responsibility for coordinating work with others.",
}


def generate_questions(items: list[dict], max_q: int = 8) -> list[dict]:
    """items: dicts with key, name, category, priority, status, evidence."""
    qs: list[dict] = []

    def add(q: str, req: str, reason: str, strong: str, follow: str = "") -> None:
        if len(qs) < max_q and all(x["question"] != q for x in qs):
            qs.append({"question": q, "requirement": req, "reason": reason, "strong_answer": strong, "follow_up": follow})

    must_first = sorted(items, key=lambda i: (i["priority"] != "must", i["category"] == tx.SOFT))
    for it in must_first:
        if it["category"] == tx.SOFT or it["status"] != tx.UNCLEAR:
            continue
        if it.get("evidence"):
            add(f"Your CV mentions: \"{it['evidence'][:140]}\". Can you describe what you personally did there with {it['name']}?",
                it["name"], "CV evidence for this requirement is unclear (listed or brief).",
                f"Specific tasks, decisions and results involving {it['name']}, with the candidate's own role clear.",
                "What would you do differently today?")
        else:
            add(f"How have you applied {it['name']} in your work or studies?", it["name"], "No clear CV evidence for this requirement.",
                f"Concrete, verifiable examples of {it['name']}.")
    for it in must_first:
        if it["category"] == tx.TECHNICAL and it["status"] == tx.DEMONSTRATED and it.get("evidence"):
            add(f"You wrote: \"{it['evidence'][:140]}\". What was the hardest part of that work and how did you solve it?",
                it["name"], "Verify depth of a skill the candidate explicitly claims.",
                "Technical detail, trade-offs considered, measurable outcome.", "How did you test or validate it?")
            break
    for it in must_first:
        if it["status"] == tx.NOT_FOUND and it["priority"] == "must" and it["category"] != tx.SOFT:
            add(f"This role requires {it['name']}. Do you have experience with it that isn't on your CV?", it["name"],
                "Must-have not found in the CV. Absence on a CV is not proof of a gap.",
                "Either concrete unlisted experience, or a realistic plan to close the gap.")
    for it in must_first:
        key = it.get("key", "")
        if key in PRACTICAL and it["category"] == tx.TECHNICAL and it["status"] != tx.NOT_FOUND:
            q, strong = PRACTICAL[key]
            add(q, it["name"], "Short practical task to verify job-relevant knowledge.", strong)
            if sum(1 for x in qs if x["reason"].startswith("Short practical")) >= 2:
                break
    for it in must_first:
        if it["category"] == tx.SOFT and it.get("key") in SOFT_QUESTIONS:
            add(SOFT_QUESTIONS[it["key"]], it["name"], "Soft skills are assessed in the interview, not from the CV.",
                "A specific situation, the candidate's actions, and the result (STAR structure).")
    if len(qs) < 5:
        add("Walk us through a project you are proud of: the goal, your role, the technology and the outcome.", "Relevant project experience",
            "General verification of hands-on experience.", "Clear ownership, technical depth, honest reflection.")
    return qs
