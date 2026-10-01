"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent  # apps/insurance_claims

FIXTURES_DIR = Path(os.getenv("FIXTURES_DIR", PROJECT_DIR / "fixtures"))
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", PROJECT_DIR / "frontend" / "dist"))
OUTBOX_DIR = Path(os.getenv("OUTBOX_DIR", BACKEND_DIR / "outbox"))

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
# Optional, only sent when set (not every model accepts it).
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT") or None
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None

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
