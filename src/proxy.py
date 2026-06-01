"""Proxy utilities for building Resin sticky proxy URLs."""

from src.config import PROXY_HOST, PROXY_PLATFORM, PROXY_PORT, PROXY_TOKEN


def build_sticky_proxy(email: str) -> str | None:
    """Build a Resin sticky proxy URL using email as Account."""
    if not PROXY_HOST:
        return None
    account = email.split("@")[0]
    platform = PROXY_PLATFORM or "Default"
    token = PROXY_TOKEN or ""
    if token:
        return f"http://{platform}.{account}:{token}@{PROXY_HOST}:{PROXY_PORT}"
    return f"http://{platform}.{account}@{PROXY_HOST}:{PROXY_PORT}"
