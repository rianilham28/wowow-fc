"""Freemail REST API backend — disposable email via a remote API."""

import asyncio
import logging
from typing import Any

from curl_cffi.requests import AsyncSession

from src.config import EMAIL_CODE_TIMEOUT, EMAIL_POLL_INTERVAL, FREEMAIL_API_TOKEN, FREEMAIL_API_URL
from src.email_provider.base import (
    EmailBackend,
    _password,
    extract_verification_link,
    iter_messages,
    message_content,
    message_id,
    rand_str,
)

logger = logging.getLogger(__name__)


class FreemailBackend(EmailBackend):
    """Disposable email provider backed by a REST API (freemail API)."""

    def __init__(self) -> None:
        self._domain_index = 0
        self._blocked_domains: set[str] = {"zztestxyz999.ccwu.cc", "indevs.in"}

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
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

    # ------------------------------------------------------------------
    # Domain management
    # ------------------------------------------------------------------

    def _is_domain_blocked(self, domain: str) -> bool:
        """Check if domain or any parent domain is blocked."""
        domain = domain.lower()
        while domain:
            if domain in self._blocked_domains:
                return True
            parts = domain.split(".", 1)
            if len(parts) <= 1:
                break
            domain = parts[1]
        return False

    def block_domain(self, domain: str) -> None:
        """Mark a domain as blocked so it won't be used again."""
        self._blocked_domains.add(domain.lower())
        logger.info("Blocked domain: %s", domain)

    async def _fetch_domains(self, *, include_blocked: bool = False) -> list[str]:
        try:
            data = await self._request("GET", "/api/domains")
            if isinstance(data, list):
                if include_blocked:
                    return data
                return [d for d in data if not self._is_domain_blocked(d)]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    # Email creation
    # ------------------------------------------------------------------

    async def create_email(self) -> tuple[str, str]:
        pw = _password()

        all_domains = await self._fetch_domains(include_blocked=True)
        if not all_domains:
            username = f"fc-{rand_str()}"
            return f"{username}@freemail.local", pw

        valid_indices = [i for i, d in enumerate(all_domains) if not self._is_domain_blocked(d)]

        if not valid_indices:
            username = f"fc-{rand_str()}"
            return f"{username}@freemail.local", pw

        start_pos = self._domain_index % len(valid_indices)
        for i in range(len(valid_indices)):
            api_idx = valid_indices[(start_pos + i) % len(valid_indices)]
            params = {"domainIndex": api_idx}

            try:
                data = await self._request("GET", "/api/generate", params=params)
                email = ""
                if isinstance(data, dict):
                    email = data.get("email", "")

                if email:
                    domain = email.split("@")[1].lower() if "@" in email else ""
                    if not self._is_domain_blocked(domain):
                        self._domain_index = (start_pos + i + 1) % len(valid_indices)
                        return email, pw
                    logger.warning("API returned blocked domain %s for index %d", domain, api_idx)
            except Exception as exc:
                logger.warning("Freemail generate error for index %d: %s", api_idx, exc)

        username = f"fc-{rand_str()}"
        return f"{username}@freemail.local", pw

    # ------------------------------------------------------------------
    # Message polling
    # ------------------------------------------------------------------

    async def _fetch_messages(self, email: str) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/emails", params={"mailbox": email, "limit": 50})
        if not isinstance(data, list):
            return []

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

        valid_msgs = [msg for msg in data if isinstance(msg, dict) and msg.get("id")]

        async def _fetch_one(msg: dict[str, Any]) -> dict[str, Any] | None:
            mid = msg["id"]
            try:
                detail = await self._request("GET", f"/api/email/{mid}")
                if isinstance(detail, dict):
                    return {
                        "id": str(mid),
                        "subject": detail.get("subject", msg.get("subject", "")),
                        "from": detail.get("sender", msg.get("sender", "")),
                        "text": detail.get("content", msg.get("content", "")),
                        "html": detail.get("html_content", msg.get("html_content", "")),
                        "received_at": detail.get("received_at", msg.get("received_at", "")),
                    }
            except Exception:
                pass
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

    async def poll_verification_link(
        self, email: str, timeout: int = EMAIL_CODE_TIMEOUT
    ) -> str | None:
        start = asyncio.get_event_loop().time()
        seen_ids: set[str] = set()

        while asyncio.get_event_loop().time() - start < timeout:
            try:
                messages = await self._fetch_messages(email)
                for msg in iter_messages(messages):
                    mid = message_id(msg)
                    if mid and mid in seen_ids:
                        continue
                    if mid:
                        seen_ids.add(mid)
                    subject = msg.get("subject", "")
                    sender = msg.get("from", "")
                    content = message_content(msg)
                    link = extract_verification_link(subject, sender, content)
                    if link:
                        return link
            except Exception as exc:
                logger.warning("Freemail poll error: %s", exc)

            await asyncio.sleep(EMAIL_POLL_INTERVAL)

        return None
