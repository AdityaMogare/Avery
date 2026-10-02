"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent  # apps/insurance_claims
REPO_DIR = PROJECT_DIR.parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines); real environment variables take precedence."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


if os.getenv("SKIP_DOTENV") != "1":
    _load_dotenv(REPO_DIR / ".env")
    _load_dotenv(BACKEND_DIR / ".env")

FIXTURES_DIR = Path(os.getenv("FIXTURES_DIR", PROJECT_DIR / "fixtures"))
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", PROJECT_DIR / "frontend" / "dist"))
OUTBOX_DIR = Path(os.getenv("OUTBOX_DIR", BACKEND_DIR / "outbox"))

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-nano")
# The groundedness judge can use a different (e.g. stronger) model; defaults to the agent model.
OPENAI_JUDGE_MODEL = os.getenv("OPENAI_JUDGE_MODEL") or OPENAI_MODEL
# Optional, only sent when set (not every model accepts it).
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT") or None
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None

# USD per 1M tokens, used for the per-turn cost estimate. Defaults: gpt-5.4-nano list price
# (developers.openai.com/docs/models/gpt-5.4-nano, checked 2026-10-01).
PRICE_INPUT_PER_M = float(os.getenv("PRICE_INPUT_PER_M", "0.20"))
PRICE_CACHED_INPUT_PER_M = float(os.getenv("PRICE_CACHED_INPUT_PER_M", "0.02"))
PRICE_OUTPUT_PER_M = float(os.getenv("PRICE_OUTPUT_PER_M", "1.25"))

# Run the LLM groundedness judge on every live reply (adds a call per turn).
LIVE_JUDGE = os.getenv("LIVE_JUDGE", "false").lower() == "true"

# SOP thresholds
MIN_VERIFIED_FIELDS = 3
MAX_FAILED_VERIFICATIONS = 3
OFF_TOPIC_OFFER_HUMAN_AFTER = 3
REFUSALS_OFFER_HUMAN_AFTER = 3
FRUSTRATION_OFFER_HUMAN_AFTER = 4


def env_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or None


def today() -> date:
    """Business date used for derived facts such as "appeal deadline passed"."""
    override = os.getenv("AGENT_TODAY")
    return date.fromisoformat(override) if override else date.today()
