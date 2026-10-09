from __future__ import annotations

import json
from datetime import date

import pytest

from talentlens import config
from talentlens.core import db
from talentlens.core.requirements import extract_requirements
from talentlens.demo.demo_data import DEMO_VACANCY

TODAY = date(2026, 10, 9)


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Fresh SQLite database and upload folder per test; real data is never touched."""
    monkeypatch.setattr(config, "VAR_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "DEMO_PDF_DIR", tmp_path / "demo_cvs")
    url = f"sqlite:///{tmp_path / 'test.db'}"
    db.configure(url)
    yield url


@pytest.fixture(scope="session")
def demo_reqs() -> list[dict]:
    return [s.to_dict() for s in extract_requirements(DEMO_VACANCY["description"])]


@pytest.fixture(scope="session")
def resources() -> list[dict]:
    return json.loads((config.DATA_DIR / "resources.json").read_text())
