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

# Provider registry: the three providers tested live. The key pasted in the UI (or set in the environment)
# picks the provider by prefix; all three are reached through their OpenAI-compatible endpoints. "models" is
# a fallback chain: when a provider retires a model (Gemini 2.5 Flash returned 404 to new keys), the client
# moves to the next one. "model_env" pins a model for that provider only.
PROVIDERS: dict[str, dict] = {
    "openai": {"base_url": None, "models": ("gpt-5.4-nano", "gpt-5.4-mini"), "prefixes": ("sk-", "sk-proj-"),
               "model_env": "OPENAI_MODEL"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "models": ("gemini-3.8-flash", "gemini-3.5-flash-lite"), "prefixes": ("AIza",),
               "model_env": "GEMINI_MODEL"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "models": ("openai/gpt-5.4-nano", "google/gemini-3.8-flash"),
                   "prefixes": ("sk-or-",), "model_env": "OPENROUTER_MODEL"},
}

# Keys from providers that aren't supported get a clear message instead of a confusing OpenAI 401
# ("sk-ant-" would otherwise match OpenAI's "sk-"). OpenRouter reaches these models with one key.
UNSUPPORTED_PREFIXES = {"sk-ant-": "Anthropic", "gsk_": "Groq", "xai-": "xAI"}


class UnsupportedKeyError(ValueError):
    pass


# Forces a provider when the key prefix is ambiguous (e.g. a DeepSeek "sk-" key with LLM_BASE_URL).
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "").lower() or None
# Generic model override. Applies only to the server's own provider (LLM_PROVIDER, or the provider of the env
# key), so a key pasted in the UI for another provider never inherits a foreign model name.
LLM_MODEL = os.getenv("LLM_MODEL") or None
# Per-provider model pins (OPENAI_MODEL, GEMINI_MODEL, OPENROUTER_MODEL); these apply to pasted keys too.
PROVIDER_MODELS = {name: os.getenv(spec["model_env"]) or None for name, spec in PROVIDERS.items()}
# The groundedness judge can use a different (e.g. stronger) model; same scoping as LLM_MODEL.
LLM_JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL") or os.getenv("OPENAI_JUDGE_MODEL") or None
# Thinking effort, sent as reasoning_effort. Gemini 3 Flash models always think, and without this they use
# the model's default level, several times slower per call than OpenAI. Low is enough for extraction and
# grounded phrasing (the verifier checks every reply); gemini-3.8-flash rejects "minimal". A rejected level
# steps down automatically (llm._EFFORT_LADDER). OpenAI's is optional, since not every model accepts it.
REASONING_EFFORT = {
    "openai": os.getenv("OPENAI_REASONING_EFFORT") or None,
    "gemini": os.getenv("GEMINI_REASONING_EFFORT") or "low",
    "openrouter": None,
}
# Custom OpenAI-compatible endpoint; overrides the provider's base URL.
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None
# SDK retries for 429s and 5xx. OPENAI_MAX_RETRIES is the older name.
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES") or os.getenv("OPENAI_MAX_RETRIES") or "6")


def detect_provider(api_key: str, explicit: str | None = None) -> str:
    """Explicit choice wins, then the longest matching key prefix, then OpenAI.

    Raises UnsupportedKeyError for keys recognisably from a provider this app doesn't support.
    """
    choice = (explicit or LLM_PROVIDER or "").lower()
    if choice in PROVIDERS:
        return choice
    for prefix, name in UNSUPPORTED_PREFIXES.items():
        if api_key.startswith(prefix):
            raise UnsupportedKeyError(f"{name} keys aren't supported. Use an OpenAI or Gemini key, or an OpenRouter "
                                      f"key to reach {name} models. Running without a model for now.")
    matches = [(len(p), name) for name, spec in PROVIDERS.items() for p in spec["prefixes"] if api_key.startswith(p)]
    return max(matches)[1] if matches else "openai"


def server_provider() -> str | None:
    if LLM_PROVIDER in PROVIDERS:
        return LLM_PROVIDER
    key = env_api_key()
    try:
        return detect_provider(key) if key else None
    except UnsupportedKeyError:
        return None


def server_scoped(value: str | None, provider: str) -> str | None:
    """A generic env override (LLM_MODEL, LLM_JUDGE_MODEL) only for the server's own provider."""
    return value if value and provider == server_provider() else None


def model_chain(provider: str, override: str | None = None) -> list[str]:
    """Models to try in order: an explicit or configured pin first, then the provider's defaults."""
    pinned = override or PROVIDER_MODELS.get(provider) or server_scoped(LLM_MODEL, provider)
    defaults = list(PROVIDERS[provider]["models"])
    return [pinned, *(m for m in defaults if m != pinned)] if pinned else defaults


def default_model(provider: str) -> str:
    return model_chain(provider)[0]


# USD per 1M tokens, used for the per-turn cost estimate. Defaults match the gpt-5.4-nano list
# price; set PRICE_* for the model actually in use.
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


ENV_KEY_VARS = ("LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY")


def env_api_key() -> str | None:
    return next((os.getenv(v) for v in ENV_KEY_VARS if os.getenv(v)), None)


def today() -> date:
    """Business date used for derived facts such as "appeal deadline passed"."""
    override = os.getenv("AGENT_TODAY")
    return date.fromisoformat(override) if override else date.today()
