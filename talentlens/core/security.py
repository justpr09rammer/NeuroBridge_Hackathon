"""Security helpers: prompt-injection detection, quote validation, PII redaction.

CV text is untrusted *data*. Nothing in this module ever executes or obeys it;
we only detect instruction-like text so a recruiter can review it.
"""
from __future__ import annotations

import re

INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)", "asks to ignore instructions"),
    (r"disregard (?:all |any )?(?:the )?(?:previous|prior|above) ", "asks to disregard instructions"),
    (r"\brank (?:this|me|the) (?:applicant|candidate)?\s*(?:as )?(?:first|#?1|top|highest)", "asks for a ranking change"),
    (r"\b(?:give|assign|award) (?:this (?:applicant|candidate)|me) (?:a )?(?:score|rating) of", "asks for a score"),
    (r"\b(?:system|developer) prompt\b", "mentions system prompt"),
    (r"\byou are (?:now )?(?:an? )?(?:ai|language model|assistant|chatgpt|claude|gpt)\b", "addresses the AI directly"),
    (r"\b(?:reveal|print|show) (?:your|the) (?:instructions|api key|secrets?)", "asks to reveal secrets"),
    (r"\bthis candidate (?:is|must be) (?:the )?(?:perfect|best|ideal) (?:match|fit)\b", "self-asserted perfect match"),
    (r"\bnote to (?:the )?(?:ai|recruiter bot|screening system|ats)\b", "addresses the screening system"),
]
_INJ = [(re.compile(p, re.IGNORECASE), why) for p, why in INJECTION_PATTERNS]


def detect_injection(text: str) -> list[dict]:
    """Return instruction-like fragments found in a document (for review, not penalty)."""
    findings: list[dict] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for rx, why in _INJ:
            if rx.search(line):
                findings.append({"line": line_no, "text": line.strip()[:240], "reason": why})
                break
    return findings


def is_instruction_like(line: str) -> bool:
    return any(rx.search(line) for rx, _ in _INJ)


_WS = re.compile(r"\s+")


def normalize_for_quote(text: str) -> str:
    """Documented normalisation for quote validation: collapse all whitespace runs
    (spaces, tabs, newlines) to a single space and strip. Case and punctuation are kept."""
    return _WS.sub(" ", text).strip()


def quote_in_source(quote: str, source: str) -> bool:
    q = normalize_for_quote(quote)
    return bool(q) and q in normalize_for_quote(source)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
_URL_PROFILE = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com|github\.com)/[\w/-]+", re.IGNORECASE)


def redact_pii(text: str, name: str = "", display_id: str = "CANDIDATE") -> str:
    """Remove direct identifiers before text is shown in blind mode or sent to an LLM."""
    out = _EMAIL.sub("[email removed]", text)
    out = _PHONE.sub("[phone removed]", out)
    out = _URL_PROFILE.sub("[profile link removed]", out)
    for part in [name] + name.split():
        part = part.strip()
        if len(part) >= 2:
            out = re.sub(r"\b" + re.escape(part) + r"\b", display_id, out)
    return out


ALLOWED_URL = re.compile(r"https?://[^\s)\]>\"']+")


def strip_unknown_urls(markdown: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Remove any URL that is not in the curated library. Returns (clean_text, removed_urls)."""
    removed: list[str] = []

    def _repl(m: re.Match[str]) -> str:
        url = m.group(0).rstrip(".,;")
        tail = m.group(0)[len(url):]
        if url in allowed:
            return m.group(0)
        removed.append(url)
        return "[link removed: not in verified library]" + tail

    return ALLOWED_URL.sub(_repl, markdown), removed
