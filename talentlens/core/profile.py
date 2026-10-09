"""Structured candidate profile extraction. Every item keeps its source line."""
from __future__ import annotations

import re
from datetime import date

from talentlens.core import taxonomy as tx
from talentlens.core.matching import DATE_RANGE, parse_lines, _match_terms, _is_header

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_NAME = re.compile(r"^[A-ZÀ-ÖØ-ÞƏŞÇĞÖÜİ][\w'’.-]+(?: [A-ZÀ-ÖØ-ÞƏŞÇĞÖÜİ][\w'’.-]+){1,3}$")


def guess_name(pages: list[str]) -> str:
    for raw in "\n".join(pages).splitlines()[:5]:
        line = raw.strip()
        if line and _NAME.match(line) and not any(ch.isdigit() for ch in line) and len(line) <= 50:
            if not re.search(r"\b(curriculum|vitae|resume|cv)\b", line, re.I):
                return line
    return ""


def extract_profile(pages: list[str], today: date | None = None) -> dict:
    today = today or date.today()
    lines = parse_lines(pages)
    text = "\n".join(pages)
    email = _EMAIL.search(text)
    phone = _PHONE.search(text)
    skills = []
    for s in tx.SKILLS:
        for ln in lines:
            if ln.instruction_like:
                continue
            terms = _match_terms(ln.text, tx.patterns_for(s.key))
            if terms:
                skills.append({"skill": s.name, "evidence": ln.text, "page": ln.page, "section": ln.section})
                break

    def section_lines(name: str) -> list[dict]:
        return [{"text": ln.text, "page": ln.page} for ln in lines if ln.section == name and not _is_header(ln) and not ln.instruction_like]

    return {
        "name": guess_name(pages),
        "email": email.group(0) if email else "",
        "phone": phone.group(0).strip() if phone else "",
        "skills": skills,
        "experience": section_lines("experience"),
        "dated_roles": [{"text": ln.text, "page": ln.page} for ln in lines if ln.section == "experience" and DATE_RANGE.search(ln.text)],
        "projects": section_lines("projects"),
        "education": section_lines("education"),
        "certifications": section_lines("certifications"),
        "languages": section_lines("languages"),
        "line_count": len(lines),
    }
