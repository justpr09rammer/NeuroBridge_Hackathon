"""Deterministic, documented scoring. No LLM is involved in any number here.

Policy (configurable):
    score = 100 * Σ(weight_i * value(status_i)) / Σ(weight_i)
    value(DEMONSTRATED)=1.0, value(UNCLEAR)=0.5, value(NOT_FOUND)=0.0 by default.

Interview-only requirements (soft skills) have weight 0 and never affect the score.
The evidence-match score is *separate* from eligibility: any must-have requirement
that is not DEMONSTRATED triggers human review; nobody is auto-rejected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from talentlens.core import taxonomy as tx

DEFAULT_POLICY = {tx.DEMONSTRATED: 1.0, tx.UNCLEAR: 0.5, tx.NOT_FOUND: 0.0}


@dataclass
class ScoreResult:
    score: float
    category_scores: dict[str, float]
    needs_review: bool
    review_reasons: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


def _g(obj: Any, attr: str, default=None):
    return obj.get(attr, default) if isinstance(obj, dict) else getattr(obj, attr, default)


def compute_score(
    items: Iterable[tuple[Any, str]],
    weights: dict[Any, float] | None = None,
    policy: dict[str, float] | None = None,
    security_flags: list[dict] | None = None,
) -> ScoreResult:
    """items: iterable of (requirement, status). ``weights`` optionally overrides
    requirement weights, keyed by requirement key (used for live re-weighting)."""
    policy = {**DEFAULT_POLICY, **(policy or {})}
    total_w = 0.0
    total = 0.0
    cat_w: dict[str, float] = {}
    cat_v: dict[str, float] = {}
    counts = {s: 0 for s in tx.STATUSES}
    reasons: list[str] = []
    for req, status in items:
        if status not in policy:
            raise ValueError(f"Unknown status {status!r}")
        key = _g(req, "key")
        params = _g(req, "params", {}) or {}
        interview_only = params.get("interview_only") or _g(req, "category") == tx.SOFT
        w = float(weights[key]) if weights and key in weights else float(_g(req, "weight", 0) or 0)
        w = 0.0 if interview_only else max(0.0, w)
        if not interview_only:
            counts[status] += 1
        if w > 0:
            total_w += w
            total += w * policy[status]
            cat = _g(req, "category")
            cat_w[cat] = cat_w.get(cat, 0.0) + w
            cat_v[cat] = cat_v.get(cat, 0.0) + w * policy[status]
        if _g(req, "priority") == "must" and not interview_only and status != tx.DEMONSTRATED:
            label = "unclear" if status == tx.UNCLEAR else "not found in CV"
            reasons.append(f"Must-have '{_g(req, 'name')}' is {label}. Verify manually.")
    score = round(100.0 * total / total_w, 1) if total_w > 0 else 0.0
    cats = {c: round(100.0 * cat_v[c] / cat_w[c], 1) for c in cat_w if cat_w[c] > 0}
    for f in security_flags or []:
        if f.get("severity") == "review":
            reasons.append(f"Document flag: {f.get('type', 'flag').replace('_', ' ')}. Review the original file.")
    return ScoreResult(score, cats, bool(reasons), reasons, counts)


def rank(rows: list[dict], score_key: str = "score") -> list[dict]:
    """Stable ranking: score desc; ties broken by fewer unverified must-haves, more
    demonstrated requirements, fewer not-found, then display id (deterministic)."""
    return sorted(
        rows,
        key=lambda r: (-float(r.get(score_key, 0.0)), int(r.get("must_unverified", 0)), -int(r.get("demonstrated", 0)),
                       int(r.get("not_found", 0)), str(r.get("display_id", ""))),
    )
