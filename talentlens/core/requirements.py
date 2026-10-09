"""Job description analysis: requirement extraction, wording review, weight normalisation.

The local parser is rule-based (Demo Mode). Live AI Mode can replace extraction via
``llm.extract_requirements_llm``; both produce the same ``RequirementSpec`` shape.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from talentlens.core import taxonomy as tx


@dataclass
class RequirementSpec:
    key: str
    name: str
    category: str
    priority: str = "must"  # must | nice
    weight: float = 10.0
    description: str = ""
    guidance: str = ""
    synonyms: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


NICE_MARKERS = re.compile(
    r"\b(nice[- ]to[- ]have|a plus|is a plus|bonus|preferred|preferably|ideally|desirable|advantage|advantageous|familiarity with|good to have|optional)\b",
    re.IGNORECASE,
)
NICE_SECTION = re.compile(r"^\s*(nice[- ]to[- ]have|bonus|preferred|pluses|good to have|desirable)", re.IGNORECASE)
BODY_SECTION = re.compile(
    r"^\s*(what you(?:'ll| will) do|responsibilities|your role|the role|about (?:us|the role|the team)|duties|benefits|what we offer)",
    re.IGNORECASE,
)
MUST_SECTION = re.compile(
    r"^\s*(requirements|must[- ]have|what you(?:'ll)? (?:need|bring)|qualifications|required|you have|who you are|minimum)",
    re.IGNORECASE,
)
YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)\b", re.IGNORECASE)
CEFR_RE = re.compile(r"\b([ABC][12])\b")
LEVEL_WORDS = {
    "native": "C2", "fluent": "C1", "advanced": "C1", "proficient": "C1", "professional": "B2",
    "upper-intermediate": "B2", "upper intermediate": "B2", "intermediate": "B1", "conversational": "B1",
    "basic": "A2", "good": "B2", "strong": "C1", "excellent": "C1",
}

DEFAULT_WEIGHTS = {
    (tx.TECHNICAL, "must"): 15, (tx.TECHNICAL, "nice"): 5,
    (tx.EXPERIENCE, "must"): 15, (tx.EXPERIENCE, "nice"): 5,
    (tx.EDUCATION, "must"): 10, (tx.EDUCATION, "nice"): 5,
    (tx.LANGUAGES, "must"): 10, (tx.LANGUAGES, "nice"): 5,
    (tx.CERTIFICATIONS, "must"): 10, (tx.CERTIFICATIONS, "nice"): 5,
    (tx.OTHER, "must"): 10, (tx.OTHER, "nice"): 5,
    (tx.SOFT, "must"): 0, (tx.SOFT, "nice"): 0,
}


def _weight(cat: str, prio: str) -> float:
    return float(DEFAULT_WEIGHTS.get((cat, prio), 10))


def _priority_for(line: str, section: str) -> str:
    # Skills that only appear in responsibilities/company text are treated as nice-to-have.
    if NICE_MARKERS.search(line) or section in ("nice", "body"):
        return "nice"
    return "must"


def extract_requirements(job_description: str) -> list[RequirementSpec]:
    """Rule-based requirement extraction. Returns a de-duplicated, editable list."""
    found: dict[str, RequirementSpec] = {}
    section = "body"
    lines = [ln.strip(" \t-•*·") for ln in job_description.splitlines()]

    def add(spec: RequirementSpec) -> None:
        existing = found.get(spec.key)
        if existing is None:
            found[spec.key] = spec
        elif existing.priority == "nice" and spec.priority == "must":
            found[spec.key] = spec  # a must-have mention wins

    for line in lines:
        if not line:
            continue
        if NICE_SECTION.match(line) and len(line) < 60:
            section = "nice"
            continue
        if MUST_SECTION.match(line) and len(line) < 60:
            section = "must"
            continue
        if BODY_SECTION.match(line) and len(line) < 60:
            section = "body"
            continue
        prio = _priority_for(line, section)

        # Technical skills and other taxonomy skills
        for skill in ([] if re.search(r"certif", line, re.IGNORECASE) else tx.SKILLS):
            if any(tx.term_regex(p).search(line) for p in skill.patterns):
                cat = skill.category
                add(RequirementSpec(
                    key=skill.key, name=skill.name, category=cat, priority=prio, weight=_weight(cat, prio),
                    description=line[:200],
                    guidance=f"Look for concrete use of {skill.name} in work or project descriptions, not only a skills list.",
                    synonyms=tx.readable_synonyms(skill.key),
                ))

        # Experience
        m = YEARS_RE.search(line)
        if m and re.search(r"experience|background|working", line, re.IGNORECASE):
            years = int(m.group(1))
            add(RequirementSpec(
                key="experience_years", name=f"{years}+ years relevant experience", category=tx.EXPERIENCE,
                priority=prio, weight=_weight(tx.EXPERIENCE, prio), description=line[:200],
                guidance="Count dated roles in relevant positions; a stated number without dated roles is unclear.",
                params={"min_years": years},
            ))

        # Education
        if re.search(r"bachelor|degree|b\.?sc|master|diploma|university", line, re.IGNORECASE):
            named = [f for f in tx.RELEVANT_FIELDS if f in line.lower()]
            strict = bool(named) and not re.search(r"related|equivalent|similar|technical field|stem", line, re.IGNORECASE)
            fields = named if strict else list(tx.RELEVANT_FIELDS)
            add(RequirementSpec(
                key="education_degree", name="Relevant degree", category=tx.EDUCATION, priority=prio,
                weight=_weight(tx.EDUCATION, prio), description=line[:200],
                guidance="A completed degree in a relevant field. Equivalent experience may be acceptable; verify with the hiring manager.",
                params={"fields": fields},
            ))

        # Languages
        for lang in tx.LANGUAGE_NAMES:
            if re.search(r"\b" + lang + r"\b", line, re.IGNORECASE):
                level = None
                cm = CEFR_RE.search(line)
                if cm:
                    level = cm.group(1)
                else:
                    for word, lvl in LEVEL_WORDS.items():
                        if re.search(r"\b" + word + r"\b", line, re.IGNORECASE):
                            level = lvl
                            break
                level = level or "B2"
                add(RequirementSpec(
                    key=f"lang_{lang.lower()}", name=f"{lang} ({level} or higher)", category=tx.LANGUAGES,
                    priority=prio, weight=_weight(tx.LANGUAGES, prio), description=line[:200],
                    guidance="Look for a stated level (CEFR, IELTS/TOEFL score, 'fluent'). A CV written in a language is not proof of level.",
                    params={"language": lang, "min_level": level},
                ))

        # Certifications
        for ckey, (cname, pats) in tx.CERT_DEFS.items():
            if any(tx.term_regex(p).search(line) for p in pats) or (cname.split()[0].lower() in line.lower() and "certif" in line.lower()):
                add(RequirementSpec(
                    key=ckey, name=cname, category=tx.CERTIFICATIONS, priority=prio,
                    weight=_weight(tx.CERTIFICATIONS, prio), description=line[:200],
                    guidance="Look for the certification name in a certifications section.",
                ))

        # Projects / portfolio
        if re.search(r"\b(portfolio|projects?|github profile)\b", line, re.IGNORECASE) and re.search(
            r"experience|demonstrable|portfolio|built|delivered|show", line, re.IGNORECASE
        ):
            add(RequirementSpec(
                key="project_experience", name="Relevant project experience", category=tx.EXPERIENCE,
                priority=prio, weight=_weight(tx.EXPERIENCE, prio) - 5, description=line[:200],
                guidance="Projects (work, academic or personal) that use the vacancy's technical skills.",
            ))

        # Soft skills: interview-only, never scored
        for skey, pats in tx.SOFT_SKILLS.items():
            if any(tx.term_regex(p).search(line) for p in pats):
                add(RequirementSpec(
                    key=f"soft_{skey}", name=tx.SOFT_NAMES[skey], category=tx.SOFT, priority=prio, weight=0,
                    description=line[:200],
                    guidance="Not scored from the CV. Assess with structured interview questions.",
                    params={"interview_only": True},
                ))

    specs = list(found.values())
    order = {c: i for i, c in enumerate(tx.CATEGORIES)}
    specs.sort(key=lambda s: (order.get(s.category, 99), 0 if s.priority == "must" else 1))
    return specs


# Wording review -------------------------------------------------------------
WORDING_RULES: list[tuple[str, str, str]] = [
    (r"\b(rock ?star|ninja|guru|wizard|superstar)\b", "Vague wording", "Jargon like this is vague and can discourage applicants. Describe the actual skills needed."),
    (r"\b(self[- ]starter|go[- ]getter|team player|good attitude|hard[- ]working|passionate)\b", "Vague qualification", "Hard to assess from a CV. Consider an observable criterion or an interview question instead."),
    (r"\b(young|youthful|energetic young|digital native|recent graduates? only)\b", "Possible age-related wording", "May suggest an age preference. Review against local employment law."),
    (r"\b(under|below|not older than|max(?:imum)?\.?) ?\d{2} ?(?:years old|y\.?o\.?)\b|\baged? \d{2}\s*[-–]\s*\d{2}\b", "Possible age limit", "Age limits are usually not job-related. Review against local employment law."),
    (r"\b(he|him|his|salesman|chairman|manpower|guys|girls)\b", "Gendered wording", "Consider gender-neutral wording (they / the candidate / salesperson)."),
    (r"\b(male|female|men only|women only)\b", "Possible sex-based requirement", "Sex-based requirements are rarely job-related. Review against local employment law."),
    (r"\bnative (english|russian|azerbaijani|speaker)\b", "Native-speaker requirement", "May exclude people by national origin. Consider a proficiency level (e.g. C1) instead."),
    (r"\b(married|single|no children|without children|family status)\b", "Family-status wording", "Family status is not job-related. Consider removing it."),
    (r"\b(religion|religious|christian|muslim|jewish|nationality|ethnicity|race)\b", "Protected-characteristic wording", "Review whether this is lawful and job-related."),
    (r"\b(attractive|good[- ]looking|presentable appearance|photo required|with photo)\b", "Appearance-related wording", "Appearance or photo requirements are rarely job-related and increase bias risk."),
    (r"\b(physically fit|able-bodied|healthy)\b", "Health/ability wording", "Only include physical requirements that are essential to the job; describe the actual task."),
]


def review_wording(job_description: str, specs: list[RequirementSpec] | None = None, title: str = "") -> list[dict]:
    """Suggestions for the recruiter. These are prompts to review, not legal judgments."""
    flags: list[dict] = []
    for line in job_description.splitlines():
        for pattern, label, advice in WORDING_RULES:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                flags.append({"label": label, "match": m.group(0), "line": line.strip()[:200], "advice": advice})
    text = f"{title}\n{job_description}".lower()
    junior = bool(re.search(r"\b(junior|entry[- ]level|graduate|intern(ship)?|trainee)\b", text))
    for s in specs or []:
        years = s.params.get("min_years") if s.params else None
        if years is None:
            continue
        if junior and years >= 3:
            flags.append({"label": "Experience requirement may be unjustified", "match": f"{years}+ years",
                          "line": s.description, "advice": "A junior/entry-level role asking for 3+ years narrows the pool. Check whether it is essential."})
        elif years >= 8:
            flags.append({"label": "High experience threshold", "match": f"{years}+ years", "line": s.description,
                          "advice": "Very high year thresholds can act as an age proxy. Consider describing the competence needed instead."})
    if not specs:
        flags.append({"label": "No requirements detected", "match": "", "line": "", "advice": "Add requirements manually in the editor."})
    return flags


def normalize_weights(weights: list[float]) -> list[float]:
    """Scale non-negative weights to sum to 100 (rounded to 1 dp, remainder on the largest)."""
    clean = [max(0.0, float(w or 0)) for w in weights]
    total = sum(clean)
    if total <= 0:
        return clean
    scaled = [round(w * 100.0 / total, 1) for w in clean]
    diff = round(100.0 - sum(scaled), 1)
    if diff and scaled:
        i = max(range(len(scaled)), key=lambda k: scaled[k])
        scaled[i] = round(scaled[i] + diff, 1)
    return scaled
