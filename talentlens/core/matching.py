"""Evidence-based matching engine (local, deterministic).

For every (candidate, requirement) pair we return DEMONSTRATED, UNCLEAR or NOT_FOUND,
plus an exact quotation from the CV's *visible* text. Principles:

* A quotation is always a full line of the extracted text, so it is a verifiable substring.
* A keyword in a skills list or without context is only UNCLEAR, never DEMONSTRATED.
* Exposure language ("familiar with", "basic", "course") caps a match at UNCLEAR.
* Absence from a CV is reported as "not found in CV", never as "lacks the skill".
* Lines that look like instructions to an AI are never used as evidence.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from talentlens.core import taxonomy as tx
from talentlens.core.security import is_instruction_like, quote_in_source

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_POINT = rf"(?:{_MON}\s+)?(?:\d{{1,2}}[/.])?(?:19|20)\d{{2}}"
DATE_RANGE = re.compile(
    rf"(?P<s>{_POINT})\s*(?:-|–|—|·|to|until)\s*(?P<e>{_POINT}|present|current|now|today|ongoing)", re.IGNORECASE
)
EXPOSURE_RE = re.compile(
    r"\b(familiar with|familiarity|basic knowledge|basics of|exposure to|introductory|intro to|learning|currently learning|"
    r"beginner|coursework|course in|online course|took a course|interested in|some knowledge|aware of|watched)\b",
    re.IGNORECASE,
)
IN_PROGRESS_RE = re.compile(r"\b(expected|ongoing|in progress|currently studying|current student|candidate for|preparing for|studying for)\b", re.IGNORECASE)
CLAIM_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)(?: of)?(?: \w+){0,4} experience|experience of (\d{1,2})\s*\+?\s*years", re.IGNORECASE)
LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]


@dataclass
class Line:
    idx: int
    text: str
    page: int
    section: str
    inline_header: bool = False
    instruction_like: bool = False


@dataclass
class ItemResult:
    requirement_key: str
    status: str
    evidence: str = ""
    page: int | None = None
    explanation: str = ""
    matched_terms: list[str] = field(default_factory=list)
    uncertainty: str = ""
    follow_up: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CVAnalysis:
    items: list[ItemResult]
    flags: list[dict]


# ---------------------------------------------------------------------------
# CV parsing
_HEADER_RES = {sec: re.compile(r"^\s*(?:" + "|".join(pats) + r")\s*:?\s*$", re.IGNORECASE) for sec, pats in tx.SECTION_HEADERS.items()}
_INLINE_RES = {sec: re.compile(r"^\s*(?:" + "|".join(pats) + r")\s*:\s*\S", re.IGNORECASE) for sec, pats in tx.SECTION_HEADERS.items()}


def parse_lines(pages: list[str]) -> list[Line]:
    lines: list[Line] = []
    section = "header"
    idx = 0
    for pno, page_text in enumerate(pages, start=1):
        for raw in page_text.splitlines():
            text = raw.strip()
            if not text:
                continue
            new_section = None
            if len(text) <= 45:
                for sec, rx in _HEADER_RES.items():
                    if rx.match(text):
                        new_section = sec
                        break
            if new_section:
                section = new_section
                lines.append(Line(idx, text, pno, section, inline_header=False))
                idx += 1
                continue
            line_section, inline = section, False
            for sec, rx in _INLINE_RES.items():
                if rx.match(text):
                    line_section, inline = sec, True
                    break
            lines.append(Line(idx, text, pno, line_section, inline, is_instruction_like(text)))
            idx += 1
    return lines


def _is_header(line: Line) -> bool:
    return any(rx.match(line.text) for rx in _HEADER_RES.values())


def _skill_count(text: str) -> int:
    return sum(1 for s in tx.SKILLS if any(rx.search(text) for rx in tx.patterns_for(s.key)))


def _is_list_like(line: Line) -> bool:
    seps = line.text.count(",") + line.text.count("|") + line.text.count("·") + line.text.count(";")
    return seps >= 2 and not tx.CONTEXT_RE.search(line.text)


def _is_stuffing(line: Line) -> bool:
    return _skill_count(line.text) >= 8 and not tx.CONTEXT_RE.search(line.text)


def _prev_same_section(lines: list[Line], line: Line) -> Line | None:
    if line.idx > 0:
        prev = lines[line.idx - 1]
        if prev.section == line.section and not _is_header(prev):
            return prev
    return None


# ---------------------------------------------------------------------------
# Generic skill matching
def _match_terms(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    out: list[str] = []
    for rx in patterns:
        m = rx.search(text)
        if m and m.group(0) not in out:
            out.append(m.group(0))
    return out


def _strength(lines: list[Line], line: Line) -> tuple[int, str]:
    """3 = used in context, 2 = named in a role/project line, 1 = listed only, 0 = exposure only."""
    if EXPOSURE_RE.search(line.text):
        return 0, "The CV indicates only exposure or learning, not hands-on use."
    if _is_stuffing(line):
        return 1, "Appears in a long keyword list without context."
    if line.section in ("skills", "languages", "certifications"):
        return 1, "Listed in a skills section without a description of how it was used."
    in_work = line.section in ("experience", "projects")
    has_ctx = bool(tx.CONTEXT_RE.search(line.text))
    if in_work:
        prev = _prev_same_section(lines, line)
        if not has_ctx and prev is not None and not _is_list_like(line) and not _is_list_like(prev):
            has_ctx = bool(tx.CONTEXT_RE.search(prev.text))  # sentence wrapped across lines
        if has_ctx and not _is_list_like(line):
            return 3, ""
        return 2, "Named in a role/project tech-stack line; how it was used is not described."
    if line.section in ("summary", "header"):
        return 1, "Mentioned in the summary; no specific role or project describes the use."
    if line.section == "education":
        return 1, "Mentioned in education (e.g. coursework), not in work or project use."
    if has_ctx:
        return 2, "Described outside the experience/projects sections."
    return 1, "Mentioned without context describing how it was used."


def match_skill(lines: list[Line], key: str, name: str, synonyms: list[str], category: str) -> ItemResult:
    if key in tx.SKILL_BY_KEY:
        patterns = tx.patterns_for(key, synonyms)
    else:  # recruiter-defined requirement: match on its name and synonyms
        patterns = tx.patterns_for("__custom__", [name] + synonyms)
    best: tuple[int, Line, list[str], str] | None = None
    implied_terms = set()
    if key in tx.SKILL_BY_KEY:
        implied_terms = {p for p in tx.SKILL_BY_KEY[key].implied_by}
    for line in lines:
        if line.instruction_like or _is_header(line):
            continue
        terms = _match_terms(line.text, patterns)
        if not terms:
            continue
        strength, why = _strength(lines, line)
        if best is None or strength > best[0]:
            best = (strength, line, terms, why)
    if best is None:
        return ItemResult(key, tx.NOT_FOUND, explanation=f"No mention of {name} or its synonyms was found in the CV.",
                          uncertainty="Absence from the CV does not prove the candidate lacks this skill.",
                          follow_up=f"Have you worked with {name}? Describe a task where you used it.")
    strength, line, terms, why = best
    via_framework = all(any(re.fullmatch(p, t, re.IGNORECASE) for p in implied_terms) for t in terms) if implied_terms else False
    note = f" (matched via {', '.join(terms)}, which implies {name})" if via_framework else ""
    if strength >= 2 and not why:
        return ItemResult(key, tx.DEMONSTRATED, line.text, line.page,
                          f"Used in context in the {line.section} section{note}.", terms)
    if strength == 2:
        return ItemResult(key, tx.DEMONSTRATED, line.text, line.page,
                          f"Named in the {line.section} section{note}. {why}", terms,
                          uncertainty="Depth of experience is not described.")
    return ItemResult(key, tx.UNCLEAR, line.text, line.page,
                      f"{name} is mentioned{note}, but the evidence is limited.", terms,
                      uncertainty=why, follow_up=f"Can you walk us through a concrete piece of work where you used {name}?")


# ---------------------------------------------------------------------------
# Experience
def _parse_point(s: str, today: date) -> int | None:
    s = s.strip().lower()
    if s in ("present", "current", "now", "today", "ongoing"):
        return today.year * 12 + today.month - 1
    ym = re.search(r"((?:19|20)\d{2})", s)
    if not ym:
        return None
    year = int(ym.group(1))
    month = 1
    mm = re.match(r"([a-z]+)", s)
    if mm and mm.group(1)[:3] in MONTHS:
        month = MONTHS[mm.group(1)[:3]]
    else:
        nm = re.match(r"(\d{1,2})[/.]", s)
        if nm and 1 <= int(nm.group(1)) <= 12:
            month = int(nm.group(1))
    return year * 12 + month - 1


def dated_roles(lines: list[Line], today: date, role_terms: tuple[str, ...] | None = tx.DEFAULT_RELEVANT_ROLE_TERMS) -> list[tuple[int, int, Line]]:
    """Dated experience-section ranges. role_terms=None returns all dated roles."""
    roles = []
    for line in lines:
        if line.section != "experience" or line.instruction_like:
            continue
        for m in DATE_RANGE.finditer(line.text):
            s, e = _parse_point(m.group("s"), today), _parse_point(m.group("e"), today)
            if s is None or e is None or e < s:
                continue
            ctx = line.text.lower()
            prev = lines[line.idx - 1].text.lower() if line.idx > 0 else ""
            nxt = lines[line.idx + 1].text.lower() if line.idx + 1 < len(lines) else ""
            if role_terms is None or any(t in f"{ctx} {prev} {nxt}" for t in role_terms):
                roles.append((s, e + 1, line))
    return roles


def _merged_months(roles: list[tuple[int, int, Line]]) -> int:
    spans = sorted((s, e) for s, e, _ in roles)
    total, cur_s, cur_e = 0, None, None
    for s, e in spans:
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def match_experience(lines: list[Line], key: str, min_years: float, today: date) -> ItemResult:
    roles = dated_roles(lines, today)
    years = round(_merged_months(roles) / 12, 1)
    if roles and years >= min_years:
        longest = max(roles, key=lambda r: r[1] - r[0])[2]
        return ItemResult(key, tx.DEMONSTRATED, longest.text, longest.page,
                          f"Dated relevant roles total about {years} years (requirement: {min_years}+).", ["dated roles"])
    claim = next((ln for ln in lines if not ln.instruction_like and CLAIM_YEARS_RE.search(ln.text)), None)
    if roles:
        line = roles[0][2]
        return ItemResult(key, tx.NOT_FOUND, line.text, line.page,
                          f"Dated relevant roles total about {years} years, below the {min_years}+ requirement.", ["dated roles"],
                          uncertainty="Undated or freelance work may not be captured." + (" The CV also states a total in prose." if claim else ""),
                          follow_up="Do you have relevant experience that is not listed with dates?")
    if claim:
        return ItemResult(key, tx.UNCLEAR, claim.text, claim.page,
                          "Experience is stated as a number, but no dated roles support it.", [],
                          uncertainty="Self-reported total without dated roles.",
                          follow_up="Could you list the roles and dates behind your stated experience?")
    other_roles = dated_roles(lines, today, role_terms=None)
    if other_roles:
        ln = other_roles[0][2]
        return ItemResult(key, tx.NOT_FOUND, ln.text, ln.page,
                          "Dated roles were found, but none appear to be in a relevant (software/data/engineering) position.", [],
                          uncertainty="Role titles may not reflect the actual work.", follow_up="Did any of your roles involve software development?")
    has_exp = any(ln.section == "experience" and not _is_header(ln) for ln in lines)
    if has_exp:
        first = next(ln for ln in lines if ln.section == "experience" and not _is_header(ln))
        return ItemResult(key, tx.UNCLEAR, first.text, first.page, "An experience section exists, but its dates could not be read.",
                          uncertainty="Dates missing or in an unrecognised format.", follow_up="When did each of your roles start and end?")
    return ItemResult(key, tx.NOT_FOUND, explanation="No dated work experience was found in the CV.",
                      uncertainty="Project or volunteer work may still be relevant.",
                      follow_up="Tell us about any professional, freelance or internship experience.")


def match_projects(lines: list[Line], key: str, tech_keys: list[str]) -> ItemResult:
    pats = [rx for k in tech_keys for rx in tx.patterns_for(k)]
    proj = [ln for ln in lines if ln.section == "projects" and not _is_header(ln) and not ln.instruction_like]
    for ln in proj + [ln for ln in lines if ln.section == "experience" and re.search(r"\bproject\b", ln.text, re.I)]:
        terms = _match_terms(ln.text, pats)
        if terms and not EXPOSURE_RE.search(ln.text) and not ln.instruction_like:
            return ItemResult(key, tx.DEMONSTRATED, ln.text, ln.page, "Project work uses the vacancy's technical skills.", terms)
    if proj:
        return ItemResult(key, tx.UNCLEAR, proj[0].text, proj[0].page, "Projects are listed, but they do not mention the vacancy's technologies.",
                          uncertainty="The technology used may simply not be written down.", follow_up="Which technologies did you use in your projects?")
    return ItemResult(key, tx.NOT_FOUND, explanation="No project descriptions were found in the CV.",
                      uncertainty="Relevant projects may exist but not be listed.", follow_up="Describe a project you built end to end.")


def match_education(lines: list[Line], key: str, fields: list[str], today: date) -> ItemResult:
    degree_rx = re.compile("|".join(tx.DEGREE_PATTERNS), re.IGNORECASE)
    fields = [f.lower() for f in (fields or tx.RELEVANT_FIELDS)]
    best: tuple[int, ItemResult] | None = None
    for ln in lines:
        if ln.instruction_like or not degree_rx.search(ln.text):
            continue
        window = " ".join(x.text for x in lines[ln.idx: ln.idx + 2]).lower()
        relevant = [f for f in fields if f in window]
        years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", window)]
        in_progress = bool(IN_PROGRESS_RE.search(window)) or bool(re.search(r"(?:19|20)\d{2}\s*[-–]\s*(present|now|current)", window, re.I)) or (years and max(years) > today.year)
        if relevant and not in_progress:
            res = (3, ItemResult(key, tx.DEMONSTRATED, ln.text, ln.page, f"Completed degree in a relevant field ({relevant[0]}).", relevant))
        elif relevant:
            res = (2, ItemResult(key, tx.UNCLEAR, ln.text, ln.page, "A relevant degree appears to be in progress.", relevant,
                                 uncertainty="Completion date is in the future or marked as ongoing.", follow_up="When do you expect to complete your degree?"))
        else:
            res = (1, ItemResult(key, tx.UNCLEAR, ln.text, ln.page, "A degree is listed, but its field may not match the requirement.", [],
                                 uncertainty="Field of study not recognised as relevant.", follow_up="How does your field of study relate to this role?"))
        if best is None or res[0] > best[0]:
            best = res
    if best:
        return best[1]
    return ItemResult(key, tx.NOT_FOUND, explanation="No degree was found in the CV.",
                      uncertainty="Equivalent practical experience may be acceptable; check with the hiring manager.",
                      follow_up="Do you have formal education or equivalent training relevant to this role?")


def _level_from(text: str) -> str | None:
    t = text.lower()
    m = re.search(r"\b([abc][12])\b", t)
    if m:
        return m.group(1).upper()
    m = re.search(r"ielts[^\d]{0,15}(\d(?:\.\d)?)", t)
    if m:
        s = float(m.group(1))
        return "C2" if s >= 8.5 else "C1" if s >= 7 else "B2" if s >= 5.5 else "B1" if s >= 4 else "A2"
    m = re.search(r"toefl[^\d]{0,15}(\d{2,3})", t)
    if m:
        s = int(m.group(1))
        return "C1" if s >= 95 else "B2" if s >= 72 else "B1" if s >= 42 else "A2"
    for word, lvl in (("native", "C2"), ("mother tongue", "C2"), ("bilingual", "C2"), ("fluent", "C1"), ("advanced", "C1"),
                      ("proficient", "C1"), ("upper-intermediate", "B2"), ("upper intermediate", "B2"), ("professional working", "B2"),
                      ("intermediate", "B1"), ("conversational", "B1"), ("elementary", "A2"), ("basic", "A2"), ("beginner", "A1")):
        if word in t:
            return lvl
    return None


def match_language(lines: list[Line], key: str, language: str, min_level: str) -> ItemResult:
    min_level = (min_level or "B2").upper()
    lang_rx = re.compile(r"\b" + re.escape(language) + r"\b", re.IGNORECASE)
    cands = [ln for ln in lines if not ln.instruction_like and (lang_rx.search(ln.text) or (language.lower() == "english" and re.search(r"\b(ielts|toefl|cambridge)\b", ln.text, re.I)))]
    # prefer lines in the languages section and lines with a level
    cands.sort(key=lambda ln: (ln.section != "languages", _level_from(ln.text) is None, ln.idx))
    if not cands:
        return ItemResult(key, tx.NOT_FOUND, explanation=f"{language} is not mentioned in the CV.",
                          uncertainty="The language a CV is written in is not used as proof of level.",
                          follow_up=f"What is your {language} level? Do you have a certificate?")
    ln = cands[0]
    level = _level_from(ln.text)
    if level is None:
        return ItemResult(key, tx.UNCLEAR, ln.text, ln.page, f"{language} is mentioned without a level.", [language],
                          uncertainty="No CEFR level, test score or proficiency word.", follow_up=f"How would you rate your {language} (CEFR level)?")
    if LEVEL_ORDER.index(level) >= LEVEL_ORDER.index(min_level):
        return ItemResult(key, tx.DEMONSTRATED, ln.text, ln.page, f"Stated {language} level ≈{level} meets the {min_level} requirement.", [language, level])
    return ItemResult(key, tx.NOT_FOUND, ln.text, ln.page, f"Stated {language} level ≈{level} is below the required {min_level}.", [language, level],
                      uncertainty="Self-reported levels can be conservative.", follow_up=f"Have you used {language} at work since this level was assessed?")


def match_certification(lines: list[Line], key: str, name: str, synonyms: list[str]) -> ItemResult:
    pats = tx.patterns_for(key, synonyms)
    for ln in lines:
        if ln.instruction_like:
            continue
        terms = _match_terms(ln.text, pats)
        if terms:
            if IN_PROGRESS_RE.search(ln.text):
                return ItemResult(key, tx.UNCLEAR, ln.text, ln.page, f"{name} appears to be in progress.", terms,
                                  uncertainty="Not yet completed.", follow_up="When do you expect to complete the certification?")
            return ItemResult(key, tx.DEMONSTRATED, ln.text, ln.page, f"{name} is listed.", terms,
                              uncertainty="Certificates are not verified against the issuer in this MVP.")
    return ItemResult(key, tx.NOT_FOUND, explanation=f"{name} was not found in the CV.", follow_up=f"Do you hold {name} or an equivalent?")


def match_soft(lines: list[Line], key: str, name: str) -> ItemResult:
    pats = tx.patterns_for(key.replace("soft_", ""))
    for ln in lines:
        terms = _match_terms(ln.text, pats)
        if terms and not ln.instruction_like:
            return ItemResult(key, tx.UNCLEAR, ln.text, ln.page, f"Interview topic, not scored. The CV mentions {name.lower()}.", terms,
                              uncertainty="Soft skills cannot be reliably judged from a CV.", follow_up=f"Tell us about a situation that shows your {name.lower()}.")
    return ItemResult(key, tx.UNCLEAR, explanation="Interview topic, not scored from the CV.",
                      uncertainty="Soft skills cannot be reliably judged from a CV.", follow_up=f"Tell us about a situation that shows your {name.lower()}.")


# ---------------------------------------------------------------------------
def _get(req: Any, attr: str, default=None):
    return req.get(attr, default) if isinstance(req, dict) else getattr(req, attr, default)


def analyse_cv(pages: list[str], requirements: list[Any], today: date | None = None) -> CVAnalysis:
    """Assess one CV against a list of requirements (dicts or ORM rows)."""
    today = today or date.today()
    lines = parse_lines(pages)
    source = "\n".join(pages)
    tech_keys = [_get(r, "key") for r in requirements if _get(r, "category") == tx.TECHNICAL] or [s.key for s in tx.SKILLS]
    items: list[ItemResult] = []
    for req in requirements:
        key, name, cat = _get(req, "key"), _get(req, "name"), _get(req, "category")
        syn = list(_get(req, "synonyms", []) or [])
        params = _get(req, "params", {}) or {}
        if params.get("interview_only") or cat == tx.SOFT:
            res = match_soft(lines, key, name)
        elif key == "experience_years" or "min_years" in params:
            res = match_experience(lines, key, float(params.get("min_years", 1)), today)
        elif key == "project_experience":
            res = match_projects(lines, key, tech_keys)
        elif key == "education_degree" or cat == tx.EDUCATION:
            res = match_education(lines, key, params.get("fields", []), today)
        elif key.startswith("lang_") or cat == tx.LANGUAGES:
            res = match_language(lines, key, params.get("language", name.split(" ")[0]), params.get("min_level", "B2"))
        elif key in tx.CERT_DEFS or cat == tx.CERTIFICATIONS:
            res = match_certification(lines, key, name, syn)
        else:
            res = match_skill(lines, key, name, syn, cat)
        # Hard guarantee: every quotation must exist in the source text.
        if res.evidence and not quote_in_source(res.evidence, source):
            res = ItemResult(key, tx.UNCLEAR, "", None, "Evidence could not be validated against the CV text.",
                             uncertainty="Quotation failed validation and was discarded.", follow_up=res.follow_up)
        items.append(res)
    return CVAnalysis(items=items, flags=document_flags(lines))


def document_flags(lines: list[Line]) -> list[dict]:
    flags = []
    inj = [ln for ln in lines if ln.instruction_like]
    for ln in inj:
        flags.append({"type": "instruction_like_text", "severity": "review", "page": ln.page, "text": ln.text[:240],
                      "detail": "Text addressed to an AI/screening system. Ignored as evidence; it does not affect the score."})
    stuffed = [ln for ln in lines if _is_stuffing(ln)]
    if stuffed:
        flags.append({"type": "possible_keyword_stuffing", "severity": "info", "page": stuffed[0].page, "text": stuffed[0].text[:240],
                      "detail": f"{len(stuffed)} line(s) list many technologies without context. Listed skills count only as 'unclear'."})
    return flags
