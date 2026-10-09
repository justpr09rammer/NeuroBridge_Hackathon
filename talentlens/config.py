"""Central configuration. All secrets come from environment variables."""
from __future__ import annotations

import os
from pathlib import Path

try:  # optional .env support
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass

ROOT_DIR = Path(__file__).resolve().parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
VAR_DIR = Path(os.getenv("TALENTLENS_VAR_DIR", ROOT_DIR / "var"))
UPLOAD_DIR = VAR_DIR / "uploads"
DEMO_PDF_DIR = VAR_DIR / "demo_cvs"

DATABASE_URL = os.getenv("TALENTLENS_DATABASE_URL", f"sqlite:///{VAR_DIR / 'talentlens.db'}")

MAX_UPLOAD_BYTES = int(os.getenv("TALENTLENS_MAX_UPLOAD_MB", "5")) * 1024 * 1024
MAX_FILES_PER_BATCH = 100
MIN_READABLE_CHARS = 120
ALLOWED_EXTENSIONS = {".pdf"}

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

LOCAL_PIPELINE_NAME = "local-rules-v1"


def anthropic_key_present() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


def ensure_dirs() -> None:
    for d in (VAR_DIR, UPLOAD_DIR, DEMO_PDF_DIR):
        d.mkdir(parents=True, exist_ok=True)
