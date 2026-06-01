"""Shared fixtures for firecrawl-creator tests."""

import sys
from pathlib import Path

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Prevent test env pollution — each test starts with no project vars."""
    for key in [
        "EMAIL_PROVIDER",
        "GMAIL_TOKENS_PATH",
        "FREEMAIL_API_URL",
        "FREEMAIL_API_TOKEN",
        "PROXY_URL",
        "PROXY_HOST",
        "PROXY_PORT",
        "PROXY_TOKEN",
        "PROXY_PLATFORM",
        "SERVER_URL",
        "SERVER_ADMIN_PASSWORD",
        "DEFAULT_COUNT",
        "DEFAULT_CONCURRENCY",
        "DEFAULT_DELAY",
        "EMAIL_CODE_TIMEOUT",
        "EMAIL_POLL_INTERVAL",
        "API_KEY_TIMEOUT",
    ]:
        monkeypatch.delenv(key, raising=False)
