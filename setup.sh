#!/usr/bin/env bash
# One-time setup: virtual environment, dependencies, database and fictional demo data.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -m venv .venv
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
python -m scripts.seed --evaluate
echo
echo "Setup complete. Start the app with: ./run.sh"
