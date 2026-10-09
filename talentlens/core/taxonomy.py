"""Skill taxonomy, synonym dictionaries and category constants.

The synonym lists are deliberately conservative: a synonym is only listed when it is
(near-)equivalent evidence for the canonical skill (e.g. "PostgreSQL" for SQL).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Requirement categories ------------------------------------------------------
TECHNICAL = "Technical skills"
EXPERIENCE = "Relevant experience"
EDUCATION = "Education"
LANGUAGES = "Languages"
CERTIFICATIONS = "Certifications"
OTHER = "Other job-related qualifications"
SOFT = "Soft skills (interview only)"

CATEGORIES = [TECHNICAL, EXPERIENCE, EDUCATION, LANGUAGES, CERTIFICATIONS, OTHER, SOFT]
SCORED_CATEGORIES = [c for c in CATEGORIES if c != SOFT]

DEMONSTRATED = "DEMONSTRATED"
UNCLEAR = "UNCLEAR"
NOT_FOUND = "NOT_FOUND"
STATUSES = [DEMONSTRATED, UNCLEAR, NOT_FOUND]


@dataclass(frozen=True)
class SkillDef:
    key: str
    name: str
    patterns: tuple[str, ...]
    category: str = TECHNICAL
    topic: str = "Software engineering"
    implied_by: tuple[str, ...] = field(default_factory=tuple)  # frameworks implying the skill


def _p(*words: str) -> tuple[str, ...]:
    return tuple(words)


SKILLS: list[SkillDef] = [
    SkillDef("python", "Python", _p(r"python"), implied_by=_p(r"django", r"flask", r"fastapi", r"pandas", r"pytest")),
    SkillDef("sql", "SQL", _p(r"sql", r"t-sql", r"pl/sql", r"postgresql", r"postgres", r"mysql", r"sqlite", r"sql server"), topic="Data"),
    SkillDef("databases", "Database knowledge", _p(r"databases?", r"postgresql", r"postgres", r"mysql", r"mongodb", r"oracle database", r"sql server", r"redis", r"schema design", r"data model(?:l)?ing"), topic="Data"),
    SkillDef("git", "Git", _p(r"git", r"github", r"gitlab", r"bitbucket", r"version control", r"pull requests?")),
    SkillDef("java", "Java", _p(r"java(?!\s*script)"), implied_by=_p(r"spring boot", r"junit")),
    SkillDef("spring_boot", "Spring Boot", _p(r"spring boot", r"springboot", r"spring framework")),
    SkillDef("docker", "Docker", _p(r"docker", r"dockerfile", r"docker-compose", r"containeri[sz]ed")),
    SkillDef("kubernetes", "Kubernetes", _p(r"kubernetes", r"k8s", r"helm")),
    SkillDef("rest_api", "REST APIs", _p(r"rest(?:ful)? apis?", r"restful", r"rest endpoints?", r"http apis?", r"openapi", r"rest services?", r"web apis?")),
    SkillDef("javascript", "JavaScript", _p(r"javascript", r"typescript", r"node\.js", r"nodejs")),
    SkillDef("react", "React", _p(r"react(?:\.js)?", r"next\.js")),
    SkillDef("aws", "AWS", _p(r"aws", r"amazon web services", r"ec2", r"s3", r"aws lambda"), topic="Cloud"),
    SkillDef("linux", "Linux", _p(r"linux", r"bash", r"shell scripting", r"ubuntu")),
    SkillDef("machine_learning", "Machine learning", _p(r"machine learning", r"scikit-learn", r"sklearn", r"tensorflow", r"pytorch", r"ml models?"), topic="Data"),
    SkillDef("data_analysis", "Data analysis", _p(r"data analysis", r"pandas", r"numpy", r"data visuali[sz]ation", r"analytics dashboards?"), topic="Data"),
    SkillDef("testing", "Automated testing", _p(r"unit tests?", r"unit testing", r"pytest", r"junit", r"test-driven", r"tdd", r"integration tests?", r"automated tests?")),
    SkillDef("messaging", "Message brokers (Kafka/RabbitMQ)", _p(r"kafka", r"rabbitmq", r"message queues?", r"message brokers?")),
    SkillDef("ci_cd", "CI/CD", _p(r"ci/cd", r"github actions", r"jenkins", r"gitlab ci", r"continuous integration")),
    SkillDef("agile", "Agile / Scrum", _p(r"agile", r"scrum", r"kanban"), category=OTHER, topic="Process"),
]

SKILL_BY_KEY = {s.key: s for s in SKILLS}

SOFT_SKILLS: dict[str, tuple[str, ...]] = {
    "communication": (r"communication", r"communicat\w+"),
    "teamwork": (r"team ?work", r"team player", r"collaborat\w+"),
    "problem_solving": (r"problem[- ]solving",),
    "leadership": (r"leadership",),
}
SOFT_NAMES = {
    "communication": "Communication",
    "teamwork": "Teamwork & collaboration",
    "problem_solving": "Problem solving",
    "leadership": "Leadership",
}

LANGUAGE_NAMES = ["English", "Azerbaijani", "Russian", "Turkish", "German", "French"]

CERT_DEFS: dict[str, tuple[str, tuple[str, ...]]] = {
    "cert_aws": ("AWS certification", (r"aws certified[\w\s-]*", r"aws solutions architect")),
    "cert_oracle_java": ("Oracle Java certification", (r"oracle certified[\w\s-]*", r"\boc[ap]\b", r"java se \d+ (?:programmer|developer)")),
    "cert_azure": ("Microsoft Azure certification", (r"microsoft certified[\w\s:-]*", r"az-\d{3}")),
    "cert_scrum": ("Scrum certification", (r"professional scrum master", r"\bpsm ?i*\b", r"certified scrum master", r"\bcsm\b")),
    "cert_ccna": ("Cisco CCNA", (r"\bccna\b",)),
}

DEGREE_PATTERNS = (
    r"bachelor(?:'s)?", r"\bb\.?\s?sc\b", r"\bb\.?\s?s\.?\b(?= in)", r"\bb\.?eng\b", r"master(?:'s)?",
    r"\bm\.?\s?sc\b", r"\bph\.?d\b", r"degree in", r"diploma in",
)
RELEVANT_FIELDS = (
    "computer science", "computer engineering", "software engineering", "information technology",
    "information systems", "mathematics", "applied mathematics", "data science", "statistics",
    "electrical engineering", "physics", "informatics",
)

CONTEXT_VERBS = (
    r"built", r"build", r"developed", r"develop", r"implemented", r"designed", r"wrote", r"written", r"created",
    r"maintained", r"deployed", r"migrated", r"optimi[sz]ed", r"automated", r"integrated", r"used", r"using",
    r"queried", r"led", r"refactored", r"shipped", r"delivered", r"configured", r"trained", r"analy[sz]ed",
    r"tested", r"reduced", r"improved", r"worked with", r"responsible for", r"contributed", r"wrote",
    r"programmed", r"modelled", r"modeled", r"scripted", r"containeri[sz]ed", r"orchestrated", r"published",
    r"set up", r"introduced", r"engineered", r"crafted", r"tuned", r"ran", r"reviewed", r"authored", r"shepherded", r"wired",
    r"powered by", r"backed by", r"on top of",
)
CONTEXT_RE = re.compile(r"\b(?:" + "|".join(CONTEXT_VERBS) + r")\b", re.IGNORECASE)

SECTION_HEADERS = {
    "experience": (r"(?:work |professional |relevant )?experience", r"employment(?: history)?", r"work history", r"career"),
    "projects": (r"(?:personal |selected |academic |side )?projects?", r"portfolio"),
    "education": (r"education", r"academic background", r"studies", r"training", r"courses"),
    "skills": (r"(?:technical |core |key )?skills", r"technologies", r"tech stack", r"tools", r"competencies", r"keywords"),
    "certifications": (r"certifications?", r"certificates?", r"licen[cs]es"),
    "languages": (r"languages?",),
    "summary": (r"summary", r"profile", r"about(?: me)?", r"objective"),
    "contact": (r"contact(?: details)?",),
    "other": (r"interests", r"hobbies", r"awards", r"volunteering", r"references", r"publications"),
}

DEFAULT_RELEVANT_ROLE_TERMS = (
    "engineer", "developer", "programmer", "software", "backend", "back-end", "frontend", "front-end",
    "full-stack", "fullstack", "data", "analyst", "devops", "sre", "qa", "intern",
)


def term_regex(pattern: str) -> re.Pattern[str]:
    """Word-boundary aware regex for a synonym pattern."""
    return re.compile(r"(?<![\w+#/.-])" + pattern + r"(?![\w+#]|-(?:script))", re.IGNORECASE)


_COMPILED: dict[str, list[re.Pattern[str]]] = {}


def patterns_for(key: str, extra: list[str] | None = None) -> list[re.Pattern[str]]:
    """Compiled patterns for a skill key plus recruiter-supplied synonyms."""
    if key not in _COMPILED:
        pats: list[str] = []
        if key in SKILL_BY_KEY:
            s = SKILL_BY_KEY[key]
            pats = list(s.patterns) + list(s.implied_by)
        elif key in SOFT_SKILLS:
            pats = list(SOFT_SKILLS[key])
        elif key in CERT_DEFS:
            pats = list(CERT_DEFS[key][1])
        _COMPILED[key] = [term_regex(p) for p in pats]
    compiled = list(_COMPILED[key])
    for syn in extra or []:
        syn = syn.strip()
        if syn:
            compiled.append(term_regex(re.escape(syn)))
    return compiled


def readable_synonyms(key: str) -> list[str]:
    """Human-readable synonym list shown in the requirement editor."""
    if key in SKILL_BY_KEY:
        s = SKILL_BY_KEY[key]
        out = [p.replace("\\", "").replace("(?:", "").replace(")?", "").replace("?", "") for p in s.patterns + s.implied_by]
        cleaned = []
        for o in out:
            o = re.sub(r"\(\?![^)]*\)", "", o)
            o = o.replace("[sz]", "s").replace("(", "").replace(")", "")
            if o and o not in cleaned:
                cleaned.append(o)
        return cleaned[:10]
    return []


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60] or "req"
