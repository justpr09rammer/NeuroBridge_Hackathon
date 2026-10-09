"""Local RAG over the curated learning-resource library.

Pipeline: skill gap -> retrieval query -> TF-IDF search over curated records
-> relevance-ranked selection with a reason -> report. Only records from the
library can ever be returned; there is no generation of links.
"""
from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from talentlens.core import taxonomy as tx

MIN_SCORE = 0.12
SKILL_TAG_BONUS = 0.6


@dataclass
class Retrieved:
    resource: dict
    score: float
    reason: str


def _doc(r: dict) -> str:
    return f"{r['title']} {r['skill'].replace('_', ' ')} {r['topic']} {r['description']}"


def build_query(skill_key: str, skill_name: str = "") -> str:
    """Normalise a missing-skill into a retrieval query."""
    parts = [skill_name or skill_key.replace("_", " ")]
    if skill_key in tx.SKILL_BY_KEY:
        parts.extend(tx.readable_synonyms(skill_key)[:5])
    elif skill_key.startswith("lang_"):
        parts.append(skill_key[5:] + " language practice")
    elif skill_key == "education_degree":
        parts.append("computer science foundations course")
    elif skill_key == "project_experience":
        parts.append("portfolio projects repositories")
    elif skill_key == "experience_years":
        parts.append("portfolio projects")
    q = " ".join(parts).lower()
    return re.sub(r"[^a-z0-9+#/ ]", " ", q)


class ResourceIndex:
    def __init__(self, resources: list[dict]):
        self.resources = resources
        self._vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        corpus = [_doc(r) for r in resources] or [""]
        self._matrix = self._vec.fit_transform(corpus)

    def search(self, skill_key: str, skill_name: str = "", k: int = 2) -> list[Retrieved]:
        if not self.resources:
            return []
        query = build_query(skill_key, skill_name)
        sims = cosine_similarity(self._vec.transform([query]), self._matrix)[0]
        out: list[Retrieved] = []
        lookup_key = "experience_years" if skill_key == "experience_years" else skill_key
        for i, r in enumerate(self.resources):
            tag_match = r["skill"] == lookup_key or (skill_key == "experience_years" and r["skill"] == "project_experience")
            score = float(sims[i]) + (SKILL_TAG_BONUS if tag_match else 0.0)
            if score < MIN_SCORE:
                continue
            if tag_match:
                reason = f"Library entry is tagged with the skill '{r['skill']}'."
            else:
                terms = sorted(set(query.split()) & set(re.findall(r"[a-z0-9+#/]+", _doc(r).lower())) - {"and", "the", "with"})
                reason = "Matches query terms: " + (", ".join(terms[:5]) if terms else "semantic similarity")
            out.append(Retrieved(r, round(score, 3), reason))
        out.sort(key=lambda x: (-x.score, x.resource["title"]))
        return out[:k]


def check_url(url: str, timeout: float = 6.0) -> tuple[str, datetime]:
    """Actually request the URL. Returns a status label; network failure is not 'broken'."""
    now = datetime.utcnow()
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "TalentLens-link-check/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - curated https URLs only
            code = resp.status
        return (f"verified (HTTP {code})" if 200 <= code < 400 else f"problem (HTTP {code})"), now
    except urllib.error.HTTPError as e:
        return f"problem (HTTP {e.code})", now
    except Exception as e:  # offline, DNS, proxy
        return f"check failed ({e.__class__.__name__}); status unknown", now
