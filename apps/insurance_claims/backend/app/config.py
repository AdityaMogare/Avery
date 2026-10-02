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

# Provider registry. The key pasted in the UI (or set in the environment) picks the provider by prefix;
# every provider except Anthropic is reached through its OpenAI-compatible endpoint.
PROVIDERS: dict[str, dict] = {
    "openai": {"base_url": None, "model": "gpt-5.4-nano", "prefixes": ("sk-", "sk-proj-")},
    "anthropic": {"base_url": None, "model": "claude-opus-5-5", "prefixes": ("sk-ant-",)},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "model": "gemini-2.5-flash", "prefixes": ("AIza",)},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-5.4-nano",
                   "prefixes": ("sk-or-",)},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b", "prefixes": ("gsk_",)},
    "xai": {"base_url": "https://api.x.ai/v1", "model": "grok-4", "prefixes": ("xai-",)},
}

# Forces a provider when the key prefix is ambiguous (e.g. a DeepSeek "sk-" key with LLM_BASE_URL).
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "").lower() or None
# Model overrides apply to whichever provider is in use; OPENAI_* names are kept for back-compat.
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or None
# The groundedness judge can use a different (e.g. stronger) model; defaults to the agent model.
LLM_JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL") or os.getenv("OPENAI_JUDGE_MODEL") or None
# Optional, only sent to OpenAI when set (not every model accepts it).
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT") or None
# Custom OpenAI-compatible endpoint; overrides the provider's base URL.
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None


def detect_provider(api_key: str, explicit: str | None = None) -> str:
    """Explicit choice wins, then the longest matching key prefix, then OpenAI."""
    choice = (explicit or LLM_PROVIDER or "").lower()
    if choice in PROVIDERS:
        return choice
    matches = [(len(p), name) for name, spec in PROVIDERS.items() for p in spec["prefixes"] if api_key.startswith(p)]
    return max(matches)[1] if matches else "openai"


def default_model(provider: str) -> str:
    return LLM_MODEL or PROVIDERS[provider]["model"]


# Run the LLM groundedness judge on every live reply (adds a call per turn).
LIVE_JUDGE = os.getenv("LIVE_JUDGE", "false").lower() == "true"

# SOP thresholds
MIN_VERIFIED_FIELDS = 3
MAX_FAILED_VERIFICATIONS = 3
OFF_TOPIC_OFFER_HUMAN_AFTER = 3
REFUSALS_OFFER_HUMAN_AFTER = 3
FRUSTRATION_OFFER_HUMAN_AFTER = 4


ENV_KEY_VARS = ("LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
                "GROQ_API_KEY", "XAI_API_KEY")


def env_api_key() -> str | None:
    return next((os.getenv(v) for v in ENV_KEY_VARS if os.getenv(v)), None)


def today() -> date:
    """Business date used for derived facts such as "appeal deadline passed"."""
    override = os.getenv("AGENT_TODAY")
    return date.fromisoformat(override) if override else date.today()
