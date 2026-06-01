"""Email provider — supports Gmail and freemail REST API."""

import asyncio
import base64
import html
import json
import logging
import os
import random
import re
import string
import time
from typing import Any
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession, Session

from src.config import (
    EMAIL_CODE_TIMEOUT,
    EMAIL_POLL_INTERVAL,
    EMAIL_PROVIDER,
    FREEMAIL_API_TOKEN,
    FREEMAIL_API_URL,
    GMAIL_TOKENS_PATH,
)

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _password() -> str:
    return f"Fc{rand_str(6)}{random.randint(100, 999)}!aA"


# ---------------------------------------------------------------------------
# Shared helpers
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


def _extract_verification_link_from_content(
    subject: str, sender: str, content: str
) -> str | None:
    urls = _extract_urls(content)

    # First pass: strict host+path match
    for url in urls:
        if _is_image(url):
            continue
        if _is_verification(url):
            return url

    # Second pass: check if message is verification-related, then match path-only
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
# Freemail Backend
# ---------------------------------------------------------------------------


async def _freemail_request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    url = f"{FREEMAIL_API_URL.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {FREEMAIL_API_TOKEN}",
        "Content-Type": "application/json",
    }
    async with AsyncSession() as client:
        resp = await client.request(
            method, url, headers=headers, params=params, json=json_body, timeout=15
        )
        resp.raise_for_status()
        return resp.json()


_DOMAIN_INDEX = 0


async def _fetch_domains() -> list[str]:
    try:
        data = await _freemail_request("GET", "/api/domains")
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


async def _freemail_create_email() -> tuple[str, str]:
    global _DOMAIN_INDEX
    pw = _password()

    params = {}
    if _DOMAIN_INDEX > 0:
        params["domainIndex"] = _DOMAIN_INDEX

    data = await _freemail_request("GET", "/api/generate", params=params or None)
    email = ""
    if isinstance(data, dict):
        email = data.get("email", "")

    if not email:
        domains = await _fetch_domains()
        if domains:
            _DOMAIN_INDEX = (_DOMAIN_INDEX + 1) % len(domains)
            params["domainIndex"] = _DOMAIN_INDEX
            data = await _freemail_request("GET", "/api/generate", params=params)
            if isinstance(data, dict):
                email = data.get("email", "")
    if not email:
        username = f"fc-{rand_str()}"
        email = f"{username}@freemail.local"

    _DOMAIN_INDEX += 1
    return email, pw


def _message_id(message: dict[str, Any]) -> str | None:
    value = message.get("id") or message.get("msgid")
    return str(value) if value else None


def _message_content(message: dict[str, Any]) -> str:
    html_content = message.get("html") or message.get("html_content") or ""
    if isinstance(html_content, list):
        html_content = " ".join(str(i) for i in html_content)
    text = message.get("text") or message.get("content") or ""
    return f"{html_content} {text}"


async def _freemail_fetch_messages(email: str) -> list[dict[str, Any]]:
    data = await _freemail_request(
        "GET", "/api/emails", params={"mailbox": email, "limit": 50}
    )
    if not isinstance(data, list):
        return []

    # Check if list endpoint already has full details (avoids N+1 queries)
    _required = {"subject", "sender", "content", "html_content"}
    if all(_required.issubset(msg.keys()) for msg in data if isinstance(msg, dict)):
        return [
            {
                "id": str(msg["id"]),
                "subject": msg.get("subject", ""),
                "from": msg.get("sender", ""),
                "text": msg.get("content", ""),
                "html": msg.get("html_content", ""),
                "received_at": msg.get("received_at", ""),
            }
            for msg in data
            if isinstance(msg, dict) and msg.get("id")
        ]

    # Fallback: fetch details concurrently instead of N+1 sequential requests
    valid_msgs = [msg for msg in data if isinstance(msg, dict) and msg.get("id")]

    async def _fetch_one(msg: dict[str, Any]) -> dict[str, Any] | None:
        mid = msg["id"]
        try:
            detail = await _freemail_request("GET", f"/api/email/{mid}")
            if isinstance(detail, dict):
                return {
                    "id": str(mid),
                    "subject": detail.get("subject", msg.get("subject", "")),
                    "from": detail.get("sender", msg.get("sender", "")),
                    "text": detail.get("content", msg.get("content", "")),
                    "html": detail.get("html_content", msg.get("html_content", "")),
                    "received_at": detail.get(
                        "received_at", msg.get("received_at", "")
                    ),
                }
        except Exception:
            pass
        # Fallback to list data on error or unexpected response
        return {
            "id": str(mid),
            "subject": msg.get("subject", ""),
            "from": msg.get("sender", ""),
            "text": msg.get("content", ""),
            "html": msg.get("html_content", ""),
            "received_at": msg.get("received_at", ""),
        }

    results = await asyncio.gather(*[_fetch_one(msg) for msg in valid_msgs])
    return [r for r in results if r is not None]


def _iter_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _date(msg: dict[str, Any]) -> str:
        return str(msg.get("date") or msg.get("received_at") or "")

    return sorted(messages, key=_date, reverse=True)


async def _freemail_poll_verification_link(
    email: str, timeout: int = EMAIL_CODE_TIMEOUT
) -> str | None:
    start = asyncio.get_event_loop().time()
    seen_ids: set[str] = set()

    while asyncio.get_event_loop().time() - start < timeout:
        try:
            messages = await _freemail_fetch_messages(email)
            for message in _iter_messages(messages):
                mid = _message_id(message)
                if mid and mid in seen_ids:
                    continue
                if mid:
                    seen_ids.add(mid)
                subject = message.get("subject", "")
                sender = message.get("from", "")
                content = _message_content(message)
                link = _extract_verification_link_from_content(subject, sender, content)
                if link:
                    return link
        except Exception as exc:
            logger.warning("Freemail poll error: %s", exc)

        await asyncio.sleep(EMAIL_POLL_INTERVAL)

    return None

# ---------------------------------------------------------------------------
# Gmail Backend
# ---------------------------------------------------------------------------


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _normalize_gmail(email: str) -> str:
    local, domain = email.lower().split("@")
    if domain == "gmail.com":
        local = local.split("+")[0].replace(".", "")
    return f"{local}@{domain}"


class GmailBackend:
    def __init__(self, tokens_path: str | None = None):
        self.tokens_path = tokens_path or os.environ.get(
            "GMAIL_TOKENS_PATH", "gmail-tokens.json"
        )
        self._tokens: dict[str, dict] = {}
        self._load_tokens()
        self._accounts: list[str] = list(self._tokens.keys())
        random.shuffle(self._accounts)
        self._rr_index = 0
        self._used_variants: set[str] = set()
        self._alias_counter = 0

    def _load_tokens(self) -> None:
        path = os.path.expanduser(self.tokens_path)
        if not os.path.exists(path):
            raise ValueError(
                f"Gmail tokens file not found: {path}. "
                f"Set GMAIL_TOKENS_PATH env var or create gmail-tokens.json"
            )
        with open(path) as f:
            self._tokens = json.load(f)
        if not self._tokens:
            raise ValueError(f"No accounts in tokens file: {path}")

    def _save_tokens(self) -> None:
        path = os.path.expanduser(self.tokens_path)
        with open(path, "w") as f:
            json.dump(self._tokens, f, indent=2)
            f.write("\n")

    def _get_valid_token(self, email: str) -> dict:
        token = self._tokens.get(email)
        if not token:
            for key, val in self._tokens.items():
                if _normalize_gmail(key) == _normalize_gmail(email):
                    token = val
                    break
        if not token:
            raise ValueError(f"No token found for {email}")
        expiry = token.get("token_expiry", 0)
        if time.time() * 1000 > expiry - 60_000:
            token = self._refresh_token(email, token)
        return token

    def _refresh_token(self, email: str, token: dict) -> dict:
        if not token.get("refresh_token"):
            raise ValueError(f"No refresh_token for {email}. Re-authorize.")
        resp = Session().post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": token["client_id"],
                "client_secret": token["client_secret"],
                "refresh_token": token["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        result = resp.json()
        token["access_token"] = result["access_token"]
        token["token_expiry"] = time.time() * 1000 + result["expires_in"] * 1000
        self._save_tokens()
        logger.info("Refreshed Gmail token for %s", email)
        return token

    def _pure_username(self, base_email: str) -> tuple[str, str]:
        local, domain = base_email.split("@")
        pure = local.replace(".", "").split("+")[0].lower()
        return pure, domain

    def _generate_alias(self, base_email: str) -> str:
        username, domain = self._pure_username(base_email)
        normalized_base = f"{username}@{domain.lower()}"
        self._used_variants.add(normalized_base)

        for _ in range(100):
            suffix = f"fc-{rand_str(6)}"
            email = f"{username}+{suffix}@{domain}"
            if email.lower() not in self._used_variants:
                self._used_variants.add(email.lower())
                return email

        suffix = f"fc-{rand_str(12)}"
        email = f"{username}+{suffix}@{domain}"
        self._used_variants.add(email.lower())
        return email

    async def poll_for_verification_link(
        self, email: str, timeout: int
    ) -> str | None:
        base_email = _normalize_gmail(email)
        token = self._get_valid_token(base_email)
        access_token = token["access_token"]

        query = f"to:{email} is:unread newer_than:1d"
        deadline = time.time() + timeout

        logger.info(
            "Polling Gmail %s (base: %s) for %ds", email, base_email, timeout
        )

        while time.time() < deadline:
            try:
                link = await self._fetch_verification_link(access_token, query)
                if link:
                    return link
            except Exception as e:
                logger.warning("Gmail poll error: %s: %s", type(e).__name__, e)
                if "401" in str(e):
                    token = self._get_valid_token(base_email)
                    access_token = token["access_token"]

            await asyncio.sleep(EMAIL_POLL_INTERVAL)

        logger.warning("Gmail poll timed out for %s", email)
        return None

    async def _fetch_verification_link(
        self, access_token: str, query: str
    ) -> str | None:
        async with AsyncSession(timeout=15) as client:
            search_resp = await client.get(
                f"{GMAIL_API_BASE}/messages",
                params={"q": query, "maxResults": 5},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            search_resp.raise_for_status()
            search_data = search_resp.json()
            messages = search_data.get("messages", [])

            if not messages:
                return None

            for msg_ref in messages:
                msg_resp = await client.get(
                    f"{GMAIL_API_BASE}/messages/{msg_ref['id']}",
                    params={"format": "full"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                msg_resp.raise_for_status()
                message = msg_resp.json()

                link = self._extract_link(message)
                if link:
                    return link
        return None

    def _extract_link(self, message: dict) -> str | None:
        headers = message.get("payload", {}).get("headers", [])
        subject = ""
        sender = ""
        for h in headers:
            name = h.get("name", "").lower()
            if name == "subject":
                subject = h.get("value", "")
            elif name == "from":
                sender = h.get("value", "")

        body = self._extract_body(message)
        content = f"{subject} {body}"
        return _extract_verification_link_from_content(subject, sender, content)

    def _extract_body(self, message: dict) -> str:
        payload = message.get("payload", {})
        body_data = payload.get("body", {}).get("data")
        if body_data:
            return _decode_base64url(body_data)

        parts = payload.get("parts", [])
        for mime_type in ["text/plain", "text/html"]:
            result = self._find_body_in_parts(parts, mime_type)
            if result:
                return result
        return ""

    def _find_body_in_parts(self, parts: list, target_mime: str) -> str | None:
        for part in parts:
            if part.get("mimeType") == target_mime and part.get("body", {}).get(
                "data"
            ):
                return _decode_base64url(part["body"]["data"])
            if part.get("parts"):
                found = self._find_body_in_parts(part["parts"], target_mime)
                if found:
                    return found
        return None


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

_gmail_backend: GmailBackend | None = None


def _get_gmail_backend() -> GmailBackend:
    global _gmail_backend
    if _gmail_backend is None:
        _gmail_backend = GmailBackend(tokens_path=GMAIL_TOKENS_PATH)
    return _gmail_backend


async def create_email() -> tuple[str, str]:
    """Create an email using the configured provider."""
    if EMAIL_PROVIDER == "gmail":
        backend = _get_gmail_backend()
        alias = await backend.generate()
        pw = _password()
        return alias, pw
    else:
        return await _freemail_create_email()

async def poll_verification_link(
    email: str, timeout: int = EMAIL_CODE_TIMEOUT
) -> str | None:
    """Poll for verification link using the configured provider."""
    if EMAIL_PROVIDER == "gmail":
        backend = _get_gmail_backend()
        return await backend.poll_for_verification_link(email, timeout=timeout)
    else:
        return await _freemail_poll_verification_link(email, timeout=timeout)
