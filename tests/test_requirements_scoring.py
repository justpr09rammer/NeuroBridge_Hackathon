import pytest

from talentlens.core import taxonomy as tx
from talentlens.core.requirements import extract_requirements, normalize_weights, review_wording
from talentlens.core.scoring import compute_score, rank


def test_extraction_categories_and_priorities(demo_reqs):
    by = {r["key"]: r for r in demo_reqs}
    assert by["python"]["category"] == tx.TECHNICAL and by["python"]["priority"] == "must"
    assert by["docker"]["priority"] == "nice"
    assert by["experience_years"]["params"]["min_years"] == 2
    assert by["lang_english"]["params"]["min_level"] == "B2"
    assert by["education_degree"]["category"] == tx.EDUCATION
    assert by["soft_communication"]["category"] == tx.SOFT and by["soft_communication"]["weight"] == 0


def test_skills_only_in_responsibilities_are_nice_to_have():
    specs = {s.key: s for s in extract_requirements("What you'll do:\n- Deploy services on Kubernetes\nRequirements:\n- Python")}
    assert specs["kubernetes"].priority == "nice"
    assert specs["python"].priority == "must"


def test_certification_line_does_not_duplicate_skill():
    keys = [s.key for s in extract_requirements("Nice to have:\n- AWS certification")]
    assert "cert_aws" in keys and "aws" not in keys


def test_wording_review_flags():
    text = "Junior developer\nWe want a young rockstar. He must be a native English speaker.\n- 5+ years of experience"
    specs = extract_requirements(text)
    labels = {f["label"] for f in review_wording(text, specs, "Junior developer")}
    assert {"Vague wording", "Possible age-related wording", "Gendered wording", "Native-speaker requirement",
            "Experience requirement may be unjustified"} <= labels


def test_weight_normalisation():
    out = normalize_weights([15, 15, 0, 7])
    assert round(sum(out), 1) == 100.0 and out[2] == 0.0
    assert normalize_weights([0, 0]) == [0.0, 0.0]


REQS = [
    {"key": "a", "name": "A", "category": tx.TECHNICAL, "priority": "must", "weight": 30},
    {"key": "b", "name": "B", "category": tx.TECHNICAL, "priority": "nice", "weight": 10},
    {"key": "c", "name": "C", "category": tx.LANGUAGES, "priority": "must", "weight": 10},
    {"key": "s", "name": "Teamwork", "category": tx.SOFT, "priority": "must", "weight": 50, "params": {"interview_only": True}},
]


def test_score_formula_and_soft_skills_excluded():
    sr = compute_score(zip(REQS, [tx.DEMONSTRATED, tx.UNCLEAR, tx.NOT_FOUND, tx.UNCLEAR]))
    assert sr.score == round(100 * (30 * 1 + 10 * 0.5 + 10 * 0) / 50, 1)
    assert sr.category_scores[tx.TECHNICAL] == round(100 * 35 / 40, 1)
    assert sr.counts == {tx.DEMONSTRATED: 1, tx.UNCLEAR: 1, tx.NOT_FOUND: 1}


def test_zero_weight_and_empty_are_safe():
    assert compute_score([]).score == 0.0
    sr = compute_score([(dict(REQS[0], weight=0), tx.DEMONSTRATED)])
    assert sr.score == 0.0


def test_must_have_triggers_review_not_rejection():
    sr = compute_score(zip(REQS, [tx.DEMONSTRATED, tx.DEMONSTRATED, tx.UNCLEAR, tx.UNCLEAR]))
    assert sr.needs_review and any("C" in r for r in sr.review_reasons)
    assert sr.score > 80  # a high score does not override the unverified must-have
    sr2 = compute_score(zip(REQS, [tx.DEMONSTRATED, tx.NOT_FOUND, tx.DEMONSTRATED, tx.UNCLEAR]))
    assert not sr2.needs_review  # nice-to-have gaps and soft skills never trigger review


def test_weight_override_and_policy():
    sr = compute_score(zip(REQS, [tx.DEMONSTRATED, tx.NOT_FOUND, tx.NOT_FOUND, tx.UNCLEAR]), weights={"a": 10, "b": 0, "c": 10})
    assert sr.score == 50.0
    sr = compute_score(zip(REQS, [tx.UNCLEAR, tx.UNCLEAR, tx.UNCLEAR, tx.UNCLEAR]), policy={tx.UNCLEAR: 0.25})
    assert sr.score == 25.0
    with pytest.raises(ValueError):
        compute_score([(REQS[0], "MAYBE")])


def test_stable_ranking_with_ties():
    rows = [{"display_id": "C2", "score": 80, "demonstrated": 3, "not_found": 1, "must_unverified": 0},
            {"display_id": "C1", "score": 80, "demonstrated": 3, "not_found": 1, "must_unverified": 0},
            {"display_id": "C3", "score": 80, "demonstrated": 3, "not_found": 1, "must_unverified": 1},
            {"display_id": "C0", "score": 90, "demonstrated": 1, "not_found": 3, "must_unverified": 2}]
    order = [r["display_id"] for r in rank(rows)]
    assert order == ["C0", "C1", "C2", "C3"]
    assert order == [r["display_id"] for r in rank(list(reversed(rows)))]
