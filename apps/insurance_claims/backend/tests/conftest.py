import os
import tempfile

os.environ.setdefault("OUTBOX_DIR", tempfile.mkdtemp(prefix="sop-outbox-"))
os.environ.setdefault("AGENT_TODAY", "2026-10-01")

import pytest  # noqa: E402

from app.fixtures import get_repo  # noqa: E402
from app.config import env_api_key  # noqa: E402
from app.pipeline import Agent  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: needs an LLM API key (OPENAI_API_KEY, GEMINI_API_KEY or OPENROUTER_API_KEY); calls the live model")


@pytest.fixture
def repo():
    return get_repo()


@pytest.fixture
def offline_agent():
    return Agent(api_key=None)


@pytest.fixture
def live_agent():
    key = env_api_key()
    if not key:
        pytest.skip("no LLM API key set")
    return Agent(api_key=key)
