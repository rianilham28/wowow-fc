"""Firecrawl registration using REST API with CloakBrowser only for token generation."""

import asyncio
import json
import re
from pathlib import Path

from cloakbrowser import launch_async
from curl_cffi.requests import RequestsError

from src.config import (
    BROWSER_RETRIES,
    CHALLENGE_DELAY,
    EMAIL_CODE_TIMEOUT,
    MAX_RETRIES,
    MCL_SCRIPT_URL,
    NETWORK_RETRY_BASE_DELAY,
    PROXY_URL,
    SIGNUP_ACTION,
    SUPABASE_AUTH_COOKIE,
    SUPABASE_CODE_VERIFIER_COOKIE,
)
from src.email_provider import poll_verification_link
from src.log import Log
from src.session import default_manager as session
from src.validate import save_account, verify_api_key

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)

# Firecrawl endpoints
SIGNUP_URL = "https://www.firecrawl.dev/signin?view=signup"
API_KEYS_URL = "https://www.firecrawl.dev/app/api-keys"
AUTH_CALLBACK_URL = "https://www.firecrawl.dev/auth/callback/exchange"
TEAM_API_URL = "https://www.firecrawl.dev/api/user/team"

# ── Response parsing helpers ────────────────────────────────────


def _parse_rsc_response(text: str) -> dict[str, bool]:
    """Inspect an RSC response text for known Firecrawl response markers."""
    return {
        "confirm_email": "confirm-email" in text,
        "session_expired": "Session expired" in text or "session_expired" in text,
        "unable": "Unable to create account" in text,
        "blocked_email": "This email address cannot be used to sign up" in text,
        "phone": "requiresSmsVerification" in text,
        "phone_true": "requiresSmsVerification" in text and "true" in text,
        "blocked": "blocked" in text.lower() or "verify your request" in text.lower(),
    }


def _extract_error_message(text: str) -> str:
    """Extract a quoted error message from an RSC response."""
    match = re.search(r'"message":"([^"]+)"', text)
    return match.group(1) if match else "Unknown error"


# ── Monocle assessment state ────────────────────────────────────


class MonocleState:
    """Cached monocleAssessment token with failure tracking.

    The token is expensive to generate (requires a headless browser),
    so we cache it globally and only regenerate after consecutive failures.
    """

    def __init__(self) -> None:
        self._token: str | None = None
        self._failures: int = 0
        self._lock = asyncio.Lock()

    async def get(self, proxy: str | None = None, log: Log | None = None) -> str | None:
        """Return a valid token, generating a fresh one if needed."""
        async with self._lock:
            if self._token and self._failures < MAX_RETRIES:
                return self._token
            self._failures = 0
            token = await self._generate(proxy, log)
            if token:
                self._token = token
            return token

    def invalidate(self) -> None:
        self._token = None

    def mark_failure(self) -> None:
        self._failures += 1

    async def _generate(self, proxy: str | None, log: Log | None = None) -> str | None:
        if log:
            log.step("Generating fresh monocleAssessment token")

        for attempt in range(BROWSER_RETRIES):
            browser = None
            try:
                browser = await launch_async(proxy=proxy)
                page = await browser.new_page()
                await page.goto(SIGNUP_URL, wait_until="load")
                await asyncio.sleep(3)

                mcl_exists = await page.evaluate("() => !!window.MCL")
                if not mcl_exists:
                    await page.add_script_tag(url=MCL_SCRIPT_URL)
                    await asyncio.sleep(3)

                assessment = await page.evaluate(
                    """() => {
                        return new Promise((resolve) => {
                            const result = window.MCL.getAssessment();
                            if (result) {
                                resolve(result);
                            } else {
                                window.MCL.configure({ onAssessment: (a) => resolve(a) });
                            }
                            setTimeout(() => resolve(null), 5000);
                        });
                    }"""
                )

                if assessment:
                    if log:
                        log.done(f"{len(assessment)} chars")
                    return assessment

                self._failures += 1
                if log:
                    log.fail("failed to generate token")
                return None

            except Exception as exc:
                if "Execution context was destroyed" in str(exc):
                    if log:
                        log.info(
                            f"Browser context destroyed, "
                            f"retrying ({attempt + 1}/{BROWSER_RETRIES})..."
                        )
                    await asyncio.sleep(NETWORK_RETRY_BASE_DELAY)
                    continue
                raise
            finally:
                if browser:
                    await browser.close()

        if log:
            log.fail(f"failed after {BROWSER_RETRIES} attempts")
        return None


# Global assessment token state
_monocle = MonocleState()


# ── Signup with retry ───────────────────────────────────────────


async def _post_with_retry(
    url: str,
    headers: dict,
    data: str,
    log: Log | None = None,
) -> tuple[object, str]:
    """POST with exponential-backoff retry on transient network errors."""
    client = session.get_async()
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.post(url, headers=headers, data=data)
            return resp, resp.text
        except (RequestsError, OSError) as exc:
            last_error = exc
            if attempt == MAX_RETRIES - 1:
                raise
            if log:
                log.info(f"Network error, retrying in {NETWORK_RETRY_BASE_DELAY**attempt}s: {exc}")
            await asyncio.sleep(NETWORK_RETRY_BASE_DELAY**attempt)

    raise last_error  # type: ignore[misc]


async def _post_plain(url: str, headers: dict, data: str) -> object:
    """Simple POST without retry logic."""
    return await session.get_async().post(url, headers=headers, data=data)


async def signup_via_rest(
    email: str,
    password: str,
    assessment: str,
    log: Log | None = None,
) -> dict:
    """Submit signup via REST API."""
    if log:
        log.step("Submitting signup via REST")

    payload = [
        email,
        password,
        {
            "teamInvitationCode": None,
            "teamInvitationName": None,
            "redirect": None,
            "monocleAssessment": assessment,
        },
    ]
    headers = {
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept": "text/x-component",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        ),
        "Origin": "https://www.firecrawl.dev",
        "Referer": SIGNUP_URL,
        "next-action": SIGNUP_ACTION,
    }

    resp, text = await _post_with_retry(SIGNUP_URL, headers, json.dumps(payload), log=log)
    markers = _parse_rsc_response(text)

    # Debug log
    if log:
        log.info(
            f"Response: status={resp.status_code} len={len(text)} "
            f"confirm={markers['confirm_email']} "
            f"session_expired={markers['session_expired']} "
            f"unable={markers['unable']} "
            f"blocked_email={markers['blocked_email']} "
            f"phone={markers['phone']}"
        )

    # Session expired → regenerate monocle token and retry
    if markers["session_expired"]:
        if log:
            log.info("Session expired, regenerating monocle token...")
        _monocle.invalidate()
        fresh = await _monocle.get()
        if fresh:
            payload[2]["monocleAssessment"] = fresh
        await _post_plain(
            SIGNUP_URL,
            {"Content-Type": "text/plain;charset=UTF-8", "Accept": "text/x-component"},
            "[]",
        )
        resp, text = await _post_plain(
            SIGNUP_URL,
            headers,
            json.dumps(payload),
        )
        markers = _parse_rsc_response(text)

    # Phone verification
    if markers["phone_true"]:
        if log:
            log.fail("phone verification required")
        return {"status": "phone_required", "message": "Phone verification required"}

    # Rate limiting / Vercel challenge
    if resp.status_code == 429:
        return await _handle_429(resp, headers, payload, log)

    if resp.status_code >= 500:
        msg = f"Server error ({resp.status_code})"
        if log:
            log.fail(msg)
        return {"status": "blocked", "message": msg}

    # Blocked by Firecrawl
    if markers["unable"]:
        error_msg = _extract_error_message(text)
        if markers["blocked"]:
            _monocle.mark_failure()
        if log:
            log.fail(error_msg)
        return {"status": "blocked", "message": error_msg}

    # Blocked email domain
    if markers["blocked_email"]:
        domain = email.split("@")[1].lower() if "@" in email else ""
        if domain:
            from src.email_provider import block_domain

            block_domain(domain)
        if log:
            log.fail(f"domain {domain} blocked by Firecrawl")
        return {"status": "blocked", "message": f"Domain {domain} blocked"}

    # Success
    if markers["confirm_email"] or resp.status_code == 200:
        cookies = dict(resp.cookies)
        if log:
            log.done()
        return {"status": "sent", "cookies": cookies}

    if log:
        log.fail(f"HTTP {resp.status_code}")
    return {"status": "unknown", "message": text[:200]}


async def _handle_429(resp, headers: dict, payload: list, log: Log | None = None) -> dict:
    """Handle HTTP 429 — rate limit or Vercel challenge."""
    is_challenge = resp.headers.get("x-vercel-mitigated", "") == "challenge"
    if is_challenge:
        if log:
            log.info(f"Vercel challenge detected, waiting {CHALLENGE_DELAY}s...")
        await asyncio.sleep(CHALLENGE_DELAY)
        try:
            retry_resp = await _post_plain(SIGNUP_URL, headers, json.dumps(payload))
            if retry_resp.status_code == 200:
                return {"status": "sent", "cookies": dict(retry_resp.cookies)}
            msg = f"Challenge retry failed ({retry_resp.status_code})"
        except Exception as exc:
            msg = f"Challenge retry failed: {exc}"
        if log:
            log.fail(msg)
        return {"status": "blocked", "message": msg}

    msg = "Rate limited (429)"
    if log:
        log.fail(msg)
    return {"status": "blocked", "message": msg}


# ── Verification and key extraction ─────────────────────────────


def _extract_api_key_from_text(text: str) -> str | None:
    """Extract the longest fc-... API key from a text blob."""
    keys = re.findall(r"fc-[a-zA-Z0-9_-]{10,}", text)
    return max(keys, key=len) if keys else None


async def complete_verification_and_get_key(
    verify_url: str,
    _email: str,
    _password: str,
    _proxy: str | None = None,
    signup_cookies: dict | None = None,
    log: Log | None = None,
) -> str | None:
    """Complete verification and extract API key via REST."""
    code_verifier = (signup_cookies or {}).get(SUPABASE_CODE_VERIFIER_COOKIE)
    if not code_verifier:
        if log:
            log.fail("no code verifier from signup")
        return None

    client = session.get_async()

    if log:
        log.step("Verifying via REST")
    client.cookies.set(SUPABASE_CODE_VERIFIER_COOKIE, code_verifier, domain=".firecrawl.dev")

    resp = await client.get(verify_url, allow_redirects=False)
    loc = resp.headers.get("location", "")
    auth_code = loc.split("code=")[1].split("&")[0] if "code=" in loc else None
    if not auth_code:
        if log:
            log.fail("no auth code from verify")
        return None

    await client.post(
        AUTH_CALLBACK_URL,
        data={"code": auth_code},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    auth_token = client.cookies.get(SUPABASE_AUTH_COOKIE, "")
    if not auth_token:
        if log:
            log.fail("no auth token after exchange")
        return None
    if log:
        log.done()

    if log:
        log.step("Extracting API key via REST")

    api_key: str | None = None
    cookies = {SUPABASE_AUTH_COOKIE: auth_token}
    client.cookies.update(cookies)

    # Method 1: Scrape API keys page
    text = (await client.get(API_KEYS_URL)).text
    api_key = _extract_api_key_from_text(text)

    # Method 2: Create via POST
    if not api_key:
        body = await client.post(
            API_KEYS_URL,
            headers={"Content-Type": "text/plain;charset=UTF-8", "Accept": "text/x-component"},
            data="[]",
        )
        api_key = _extract_api_key_from_text(body.text)

    # Method 3: Team API
    if not api_key:
        resp = await client.get(TEAM_API_URL)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data.get("apiKey"), str) and data["apiKey"].startswith("fc-"):
                api_key = data["apiKey"]
            else:
                for k in data.get("apiKeys", []):
                    if isinstance(k, dict) and k.get("key", "").startswith("fc-"):
                        api_key = k["key"]
                        break

    if api_key:
        if log:
            log.done()
        return api_key
    if log:
        log.fail("no API key found")
    return None


async def create_account_rest(
    _index: int,
    _total: int,
    email: str,
    password: str,
    proxy: str | None = None,
    log: Log | None = None,
) -> str | None:
    """Create account using REST API with CloakBrowser only for token generation."""

    _proxy = proxy if proxy is not None else (PROXY_URL or None)

    if _proxy and log:
        log.info(f"Using proxy: {_proxy[:40]}...")

    try:
        assessment = await _monocle.get(proxy=_proxy, log=log)
        if not assessment:
            if log:
                log.error("Failed to generate monocleAssessment")
            return None

        result = await signup_via_rest(email, password, assessment, log=log)

        if result["status"] == "phone_required":
            if log:
                log.error("Phone verification required - skipping")
            return None

        if result["status"] != "sent":
            if log:
                log.error(f"Signup failed: {result.get('message', 'unknown')}")
            return None

        if log:
            log.step("Waiting for verification email")
        verify_url = await poll_verification_link(email, timeout=EMAIL_CODE_TIMEOUT)
        if not verify_url:
            if log:
                log.fail("timeout")
            return None
        if log:
            log.done("found")

        signup_cookies = result.get("cookies")
        api_key = await complete_verification_and_get_key(
            verify_url, email, password, None, signup_cookies, log=log
        )

        if not api_key:
            if log:
                log.error("Failed to get API key")
            return None

        if log:
            log.step("Verifying API key")
        verify_status = await verify_api_key(api_key, log=log)

        if verify_status is not True:
            if log:
                log.fail("verification failed")
            return None
        if log:
            log.done()

        save_account(email, password, api_key)

        from src.upload import upload_key

        await upload_key(email, api_key, log=log)

        if log:
            log.ok("Registration successful")
            log.detail(f"Email: {email}")
            log.detail(f"Password: {password}")
            log.detail(f"Key: {api_key}")
        return api_key

    except Exception as exc:
        if log:
            log.error(f"Error: {exc}")
        return None
