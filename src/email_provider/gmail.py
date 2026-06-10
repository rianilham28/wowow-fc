"""Gmail OAuth backend — real Gmail mailboxes via the Gmail API."""

import asyncio
import json
import logging
import os
import random
import time

from curl_cffi.requests import AsyncSession

from src.config import EMAIL_CODE_TIMEOUT, EMAIL_POLL_INTERVAL
from src.email_provider.base import (
    EmailBackend,
    _password,
    decode_base64url,
    extract_verification_link,
    normalize_gmail,
    rand_str,
)
from src.session import default_manager as session

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailBackend(EmailBackend):
    """Real Gmail mailbox backend using OAuth 2.0 and the Gmail REST API."""

    def __init__(self, tokens_path: str | None = None) -> None:
        self.tokens_path = tokens_path or os.environ.get("GMAIL_TOKENS_PATH", "gmail-tokens.json")
        self._tokens: dict[str, dict] = {}
        self._load_tokens()
        self._accounts: list[str] = list(self._tokens.keys())
        random.shuffle(self._accounts)
        self._rr_index = 0
        self._used_variants: set[str] = set()
        self._alias_counter = 0

    # ------------------------------------------------------------------
    # Token persistence
    # ------------------------------------------------------------------

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

    async def _get_valid_token(self, email: str) -> dict:
        token = self._tokens.get(email)
        if not token:
            for key, val in self._tokens.items():
                if normalize_gmail(key) == normalize_gmail(email):
                    token = val
                    break
        if not token:
            raise ValueError(f"No token found for {email}")
        expiry = token.get("token_expiry", 0)
        if time.time() * 1000 > expiry - 60_000:
            token = await self._refresh_token(email, token)
        return token

    async def _refresh_token(self, email: str, token: dict) -> dict:
        if not token.get("refresh_token"):
            raise ValueError(f"No refresh_token for {email}. Re-authorize.")
        client = session.get_async()
        resp = await client.post(
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

    # ------------------------------------------------------------------
    # Alias generation
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # EmailBackend interface
    # ------------------------------------------------------------------

    async def create_email(self) -> tuple[str, str]:
        """Pick an account in round-robin and generate a +alias."""
        if not self._accounts:
            raise ValueError("No Gmail accounts available")
        base = self._accounts[self._rr_index % len(self._accounts)]
        self._rr_index += 1
        alias = self._generate_alias(base)
        return alias, _password()

    def block_domain(self, domain: str) -> None:
        """Gmail backends don't have domain-level blocking — no-op."""
        pass

    async def poll_verification_link(
        self, email: str, timeout: int = EMAIL_CODE_TIMEOUT
    ) -> str | None:
        base_email = normalize_gmail(email)
        token = await self._get_valid_token(base_email)
        access_token = token["access_token"]

        query = f"to:{email} is:unread newer_than:1d"
        deadline = time.time() + timeout

        logger.info("Polling Gmail %s (base: %s) for %ds", email, base_email, timeout)

        while time.time() < deadline:
            try:
                link = await self._fetch_verification_link(access_token, query)
                if link:
                    return link
            except Exception as e:
                logger.warning("Gmail poll error: %s: %s", type(e).__name__, e)
                if "401" in str(e):
                    token = await self._get_valid_token(base_email)
                    access_token = token["access_token"]

            await asyncio.sleep(EMAIL_POLL_INTERVAL)

        logger.warning("Gmail poll timed out for %s", email)
        return None

    async def _fetch_verification_link(self, access_token: str, query: str) -> str | None:
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
        return extract_verification_link(subject, sender, content)

    def _extract_body(self, message: dict) -> str:
        payload = message.get("payload", {})
        body_data = payload.get("body", {}).get("data")
        if body_data:
            return decode_base64url(body_data)

        parts = payload.get("parts", [])
        for mime_type in ["text/plain", "text/html"]:
            result = self._find_body_in_parts(parts, mime_type)
            if result:
                return result
        return ""

    @staticmethod
    def _find_body_in_parts(parts: list, target_mime: str) -> str | None:
        for part in parts:
            if part.get("mimeType") == target_mime and part.get("body", {}).get("data"):
                return decode_base64url(part["body"]["data"])
            if part.get("parts"):
                found = GmailBackend._find_body_in_parts(part["parts"], target_mime)
                if found:
                    return found
        return None
