#!/usr/bin/env bash
# Launch the Streamlit app (http://localhost:8501). Pass "api" to also start the REST API on :8000.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate
if [ "${1:-}" = "api" ]; then
  python -m uvicorn api.main:app --port 8000 &
  API_PID=$!
  trap 'kill $API_PID 2>/dev/null || true' EXIT
  echo "REST API: http://localhost:8000/docs"
fi
python -m streamlit run app.py --server.port 8501
