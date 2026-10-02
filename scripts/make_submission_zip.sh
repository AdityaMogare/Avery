#!/usr/bin/env bash
# Build the submission zip without installed dependencies or build output (limit: 50MB).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-sop-guided-conversational-agent.zip}"
rm -f "$OUT"
zip -rq "$OUT" . \
  -x "*.git/*" "*node_modules/*" "*/dist/*" "*.venv/*" "*__pycache__/*" "*.pytest_cache/*" \
     "*/outbox/*" "*.DS_Store" "*.env" "*.claude/*" "*.zip"
du -h "$OUT"
unzip -l "$OUT" | tail -1
