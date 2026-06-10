"""Abstract email backend + shared helpers for URL extraction and verification link parsing."""

import base64
import html
import logging
import random
import re
import string
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Randomisation helpers
# ---------------------------------------------------------------------------

def rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _password() -> str:
    return f"Fc{rand_str(6)}{random.randint(100, 999)}!aA"


# ---------------------------------------------------------------------------
# Verification link extraction (shared by all backends)
# ---------------------------------------------------------------------------

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp")
_VERIFY_PATH_HINTS = ("verif", "confirm", "magic", "signup", "signin", "callback")
_VERIFY_HOST_HINTS = ("firecrawl", "clerk")
_MSG_HINTS = ("verify", "verification", "confirm", "magic link", "sign in", "firecrawl")
_VERIFY_TOKENS = ("verif", "confirm", "magic", "auth", "callback", "signin", "signup")


def _is_image(url: str) -> bool:
    return any(url.lower().rstrip("/").endswith(ext) for ext in _IMAGE_EXTS)


def _is_verification(url: str) -> bool:
    lowered = url.lower()
    parsed = urlparse(lowered)
    path_ok = any(token in (parsed.path or "") for token in _VERIFY_PATH_HINTS)
    host_ok = any(token in (parsed.netloc or "") for token in _VERIFY_HOST_HINTS)
    return path_ok and host_ok


def _extract_urls(text: str) -> list[str]:
    return [
        html.unescape(raw).rstrip(").,;").rstrip("#")
        for raw in re.findall(r"https?://[^\s<>\"']+", text, re.IGNORECASE)
    ]


def extract_verification_link(subject: str, sender: str, content: str) -> str | None:
    urls = _extract_urls(content)

    for url in urls:
        if _is_image(url):
            continue
        if _is_verification(url):
            return url

    combined = f"{sender} {subject} {content[:4000]}".lower()
    if not any(token in combined for token in _MSG_HINTS):
        return None

    for url in urls:
        if _is_image(url):
            continue
        lowered = url.lower()
        if any(token in lowered for token in _VERIFY_TOKENS):
            return url
    return None


# ---------------------------------------------------------------------------
# Gmail-specific helpers (shared with any future OAuth backend)
# ---------------------------------------------------------------------------

def decode_base64url(data: str) -> str:
    padded = data + "=" * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def normalize_gmail(email: str) -> str:
    local, domain = email.lower().split("@")
    if domain == "gmail.com":
        local = local.split("+")[0].replace(".", "")
    return f"{local}@{domain}"


# ---------------------------------------------------------------------------
# Generic message-iteration helpers
# ---------------------------------------------------------------------------

def message_id(message: dict[str, Any]) -> str | None:
    value = message.get("id") or message.get("msgid")
    return str(value) if value else None


def message_content(message: dict[str, Any]) -> str:
    html_content = message.get("html") or message.get("html_content") or ""
    if isinstance(html_content, list):
        html_content = " ".join(str(i) for i in html_content)
    text = message.get("text") or message.get("content") or ""
    return f"{html_content} {text}"


def iter_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _date(msg: dict[str, Any]) -> str:
        return str(msg.get("date") or msg.get("received_at") or "")

    return sorted(messages, key=_date, reverse=True)


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------


class EmailBackend(ABC):
    """Interface that every email provider backend must implement."""

    @abstractmethod
    async def create_email(self) -> tuple[str, str]:
        """Create a new email address and return (email, password)."""
        ...

    @abstractmethod
    async def poll_verification_link(
        self, email: str, timeout: int
    ) -> str | None:
        """Poll the mailbox for a verification link."""
        ...

    @abstractmethod
    def block_domain(self, domain: str) -> None:
        """Optionally blacklist a domain so it won't be reused."""
        ...
