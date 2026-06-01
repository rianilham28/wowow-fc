"""Firecrawl registration using REST API with CloakBrowser only for token generation."""

import asyncio
import json
import re
from pathlib import Path

from cloakbrowser import launch_async
from curl_cffi.requests import AsyncSession, RequestsError

from src.config import (
    EMAIL_CODE_TIMEOUT,
    MCL_SCRIPT_URL,
    PROXY_HOST,
    PROXY_URL,
    SIGNUP_ACTION,
    SUPABASE_AUTH_COOKIE,
    SUPABASE_CODE_VERIFIER_COOKIE,
)
from src.email_provider import create_email, poll_verification_link
from src.log import Log
from src.validate import save_account, verify_api_key
from src.proxy import build_sticky_proxy

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)

# Firecrawl endpoints
SIGNUP_URL = "https://www.firecrawl.dev/signin?view=signup"


_cached_assessment: str | None = None
_assessment_failures: int = 0


async def get_monocle_assessment(proxy: str | None = None, log: Log | None = None) -> str | None:
    """Generate monocleAssessment token using CloakBrowser (cached for reuse)."""
    global _cached_assessment, _assessment_failures

    if _cached_assessment and _assessment_failures < 3:
        return _cached_assessment

    _assessment_failures = 0
    if log:
        log.step("Generating fresh monocleAssessment token")
    browser = await launch_async(proxy=proxy)

    try:
        page = await browser.new_page()
        await page.goto("https://www.firecrawl.dev/signin?view=signup", wait_until="load")
        await asyncio.sleep(2)

        # Load MCL if not already loaded
        mcl_exists = await page.evaluate("() => !!window.MCL")
        if not mcl_exists:
            await page.add_script_tag(url=MCL_SCRIPT_URL)
            await asyncio.sleep(3)

        # Get assessment
        assessment = await page.evaluate("""() => {
            return new Promise((resolve) => {
                const result = window.MCL.getAssessment();
                if (result) {
                    resolve(result);
                } else {
                    window.MCL.configure({ onAssessment: (a) => resolve(a) });
                }
                setTimeout(() => resolve(null), 5000);
            });
        }""")

        if assessment:
            _cached_assessment = assessment
            if log:
                log.done(f"{len(assessment)} chars")
        else:
            _assessment_failures += 1
            if log:
                log.fail("failed to generate token")

        return assessment
    finally:
        await browser.close()


async def signup_via_rest(
    email: str, password: str, assessment: str, proxy: str | None = None, log: Log | None = None
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
        }
    ]

    headers = {
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept": "text/x-component",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",  # noqa: E501
        "Origin": "https://www.firecrawl.dev",
        "Referer": "https://www.firecrawl.dev/signin?view=signup",
        "next-action": SIGNUP_ACTION,
    }

    async with AsyncSession(impersonate="chrome", proxy=proxy) as s:
        # Retry on network errors (not HTTP 429/5xx)
        resp = None
        for _attempt in range(3):
            try:
                resp = await s.post(SIGNUP_URL, headers=headers, data=json.dumps(payload))
                break
            except (RequestsError, OSError) as exc:
                if _attempt == 2:
                    raise
                if log:
                    log.info(f"Network error, retrying in {2 ** _attempt}s: {exc}")
                await asyncio.sleep(2 ** _attempt)

        # Type guard: resp is always set after loop (errors re-raise on last attempt)
        assert resp is not None

        # Parse RSC response
        text = resp.text

        # Check for phone verification
        if "requiresSmsVerification" in text and "true" in text:
            if log:
                log.fail("phone verification required")
            return {"status": "phone_required", "message": "Phone verification required"}
        # Session expired → CSR token stale + monocle token needs regen
        if 'Session expired' in text or 'session_expired' in text:
            if log: log.info('Session expired, regenerating monocle token...')
            global _cached_assessment
            _cached_assessment = None
            fresh = await get_monocle_assessment()
            if fresh:
                payload[2]['monocleAssessment'] = fresh
            # Refresh CSRF and retry
            await s.post(SIGNUP_URL,
                headers={'Content-Type': 'text/plain;charset=UTF-8','Accept': 'text/x-component'},
                data='[]')
            resp = await s.post(SIGNUP_URL, headers=headers, data=json.dumps(payload))
            text = resp.text
        # Non-200 status codes
        if resp.status_code == 429:
            msg = 'Rate limited (429)'
            if log: log.fail(msg)
            return {"status": "blocked", "message": msg}
        if resp.status_code >= 500:
            msg = f'Server error ({resp.status_code})'
            if log: log.fail(msg)
            return {"status": "blocked", "message": msg}

        # Check for errors — keep specific failure strings only, not generic "error"
        # (RSC payloads contain "error" in chunk names leading to false positives)
        if "Unable to create account" in text:
            # Extract error message
            msg_match = re.search(r'"message":"([^"]+)"', text)
            error_msg = msg_match.group(1) if msg_match else "Unknown error"
            # Track assessment failures (sign-up blocked = bad token)
            if "blocked" in text.lower() or "verify your request" in text.lower():
                global _assessment_failures
                _assessment_failures += 1
            if log:
                log.fail(error_msg)
            return {"status": "blocked", "message": error_msg}

        # Check for email confirmation
        if "confirm-email" in text:
            cookies = dict(resp.cookies)
            if log:
                log.done()
            return {"status": "sent", "cookies": cookies}

        # Fallback: if 200 but no clear indicator
        if resp.status_code == 200:
            cookies = dict(resp.cookies)
            if log:
                log.done()
            return {"status": "sent", "cookies": cookies}

        if log:
            log.fail(f"HTTP {resp.status_code}")
        return {"status": "unknown", "message": text[:200]}


async def complete_verification_and_get_key(
    verify_url: str, _email: str, _password: str, _proxy: str | None = None,
    signup_cookies: dict | None = None, log: Log | None = None
) -> str | None:
    """Complete verification via REST + extract API key via REST.
    Uses curl_cffi for full PKCE auth exchange (no browser needed).
    """
    api_key = None
    code_verifier = (signup_cookies or {}).get(
        SUPABASE_CODE_VERIFIER_COOKIE
    )
    if not code_verifier:
        if log:
            log.fail("no code verifier from signup")
        return None

    if log:
        log.step("Verifying via REST")
    async with AsyncSession(impersonate="chrome", proxy=_proxy) as s:
        verifier = SUPABASE_CODE_VERIFIER_COOKIE
        s.cookies.set(verifier, code_verifier, domain=".firecrawl.dev")
        # GET verify link → 303 redirect with auth code
        resp = await s.get(verify_url, allow_redirects=False)
        loc = resp.headers.get("location", "")
        auth_code = loc.split("code=")[1].split("&")[0] if "code=" in loc else None
        if not auth_code:
            if log:
                log.fail("no auth code from verify")
            return None
        # Exchange code for session token
        await s.post("https://www.firecrawl.dev/auth/callback/exchange",
            data={"code": auth_code},
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        auth_token = s.cookies.get(SUPABASE_AUTH_COOKIE, "")
        if not auth_token:
            if log:
                log.fail("no auth token after exchange")
            return None
    if log:
        log.done()

    if log:
        log.step("Extracting API key via REST")
    cookies = {SUPABASE_AUTH_COOKIE: auth_token}
    async with AsyncSession(impersonate="chrome", cookies=cookies, proxy=_proxy) as s:
        # Method 1: API keys page
        text = (await s.get("https://www.firecrawl.dev/app/api-keys")).text
        keys = re.findall(r"fc-[a-zA-Z0-9_-]{10,}", text)
        if keys:
            api_key = max(keys, key=len)
        # Method 2: Create via POST
        if not api_key:
            body = await s.post(
                "https://www.firecrawl.dev/app/api-keys",
                headers={
                    "Content-Type": "text/plain;charset=UTF-8",
                    "Accept": "text/x-component",
                },
                data="[]",
            )
            keys = re.findall(r"fc-[a-zA-Z0-9_-]{10,}", body.text)
            if keys:
                api_key = max(keys, key=len)
        # Method 3: Team API
        if not api_key:
            resp = await s.get("https://www.firecrawl.dev/api/user/team")
            if resp.status_code == 200:
                data = resp.json()
                api_key = data.get("apiKey", "") or ""
                for k in data.get("apiKeys", []):
                    if isinstance(k, dict) and k.get("key", "").startswith("fc-"):
                        api_key = k["key"]
                        break

    if api_key and isinstance(api_key, str) and api_key.startswith("fc-"):
        if log:
            log.done()
        return api_key
    if log:
        log.fail("no API key found")
    return None


async def create_account_rest(
    _index: int, _total: int, email: str, password: str,
    proxy: str | None = None, log: Log | None = None
) -> str | None:
    """Create account using REST API with CloakBrowser only for token generation."""

    # Priority: CLI proxy > sticky proxy > static proxy
    if proxy is not None:
        _proxy = proxy if proxy else None
    elif PROXY_HOST:
        _proxy = build_sticky_proxy(email)
        if log:
            log.info(f"Using sticky proxy for {email.split('@')[0]}")
    else:
        _proxy = PROXY_URL or None

    try:
        # Step 1: Generate monocleAssessment token
        assessment = await get_monocle_assessment(None, log=log)
        if not assessment:
            if log:
                log.error("Failed to generate monocleAssessment")
            return None

        # Step 2: Submit signup via REST
        result = await signup_via_rest(email, password, assessment, proxy=_proxy, log=log)

        if result["status"] == "phone_required":
            if log:
                log.error("Phone verification required - skipping")
            return None

        if result["status"] != "sent":
            if log:
                log.error(f"Signup failed: {result.get('message', 'unknown')}")
            return None

        # Step 3: Poll for verification email
        if log:
            log.step("Waiting for verification email")
        verify_url = await poll_verification_link(email, timeout=EMAIL_CODE_TIMEOUT)
        if not verify_url:
            if log:
                log.fail("timeout")
            return None
        if log:
            log.done("found")

        # Step 4: Complete verification and get API key
        signup_cookies = result.get("cookies")
        api_key = await complete_verification_and_get_key(
            verify_url, email, password, _proxy, signup_cookies, log=log
        )

        if not api_key:
            if log:
                log.error("Failed to get API key")
            return None

        # Step 5: Verify and save
        if log:
            log.step("Verifying API key")
        verify_status = verify_api_key(api_key, log=log)

        if verify_status is not True:
            if log:
                log.fail("verification failed")
            return None
        if log:
            log.done()

        save_account(email, password, api_key)

        from src.upload import upload_key
        upload_key(email, api_key, log=log)

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


async def main():
    """Test the REST-based registration."""
    email, password = await create_email()
    result = await create_account_rest(1, 1, email, password)

    if result:
        print(f"\nSuccess! API Key: {result}")
    else:
        print("\nFailed to create account")


if __name__ == "__main__":
    asyncio.run(main())
