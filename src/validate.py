"""API key extraction from page content and live verification against Firecrawl API."""

import os
import re
import threading
from collections.abc import Callable
from pathlib import Path

from curl_cffi.requests import Session
from curl_cffi.requests.errors import RequestsError

from src.config import API_KEY_TIMEOUT
from src.log import Log

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
_SAVE_FILE = os.path.join(_PROJECT_ROOT, "firecrawl_accounts.txt")
_SAVE_LOCK = threading.Lock()

TEAM_API_URL = "https://www.firecrawl.dev/api/user/team"


def save_account(email: str, password: str, api_key: str) -> None:
    with _SAVE_LOCK, open(_SAVE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{email},{password},{api_key}\n")


async def fetch_api_key_from_team_api(page) -> str | None:
    """Fetch API key from /api/user/team endpoint using browser session."""
    try:
        resp = await page.request.get(TEAM_API_URL)
        if resp.status != 200:
            return None
        data = await resp.json()
        api_key = data.get("apiKey", "")
        if api_key and api_key.startswith("fc-"):
            return api_key
        # Fallback: check apiKeys array
        for key_obj in data.get("apiKeys", []):
            key = key_obj.get("key", "")
            if key and key.startswith("fc-"):
                return key
    except Exception:
        pass
    return None

async def extract_api_key(page) -> str | None:
    import asyncio

    await asyncio.sleep(3)
    selectors = [
        'code:has-text("fc-")',
        '[data-testid="api-key"]',
        ".api-key",
        'input[value^="fc-"]',
        'span:has-text("fc-")',
    ]
    for sel in selectors:
        els = await page.query_selector_all(sel)
        for el in els:
            raw = await el.inner_text()
            if not raw:
                raw = await el.get_attribute("value") or ""
            match = re.search(r"fc-[a-zA-Z0-9_-]{20,}", raw)
            if match:
                return match.group(0)

    html = str(await page.content())
    matches = re.findall(r"fc-[a-zA-Z0-9_-]{20,}", html)
    if matches:
        return str(max(matches, key=len))
    return None


def verify_api_key(api_key: str, log: Log | None = None) -> bool | None:
    transient_errors = (
        RequestsError,
        OSError,
    )
    last_error = None

    for attempt in range(1, 4):
        try:
            resp = Session().post(
                "https://api.firecrawl.dev/v2/scrape",
                json={"url": "https://example.com"},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=API_KEY_TIMEOUT,
            )
            break
        except transient_errors as exc:
            last_error = exc
            if attempt < 3:
                if log:
                    log.info(f"Retry ({attempt}/3): {exc}")
                import time
                time.sleep(attempt)
                continue
            if log:
                log.fail(str(exc))
            return None
        except Exception as exc:
            if log:
                log.fail(str(exc))
            return False
    else:
        if log:
            log.fail(f"no response: {last_error}")
        return None

    if resp.status_code == 200:
        return True

    preview = resp.text.strip().replace("\n", " ")[:160]
    msg = f"HTTP {resp.status_code}"
    if preview:
        msg += f" {preview}"
    if log:
        log.fail(msg)
    return False

async def extract_and_verify_key(
    page,
    email: str,
    password: str,
    navigate_to_api_keys_fn: Callable | None = None,
    create_api_key_fn: Callable | None = None,
    log: Log | None = None
) -> str | None:
    # Primary: fetch from team API (most reliable)
    if log:
        log.step("Fetching API key from team API")
    api_key = await fetch_api_key_from_team_api(page)
    if api_key and log:
        log.done()

    # Fallback: extract from page content
    if not api_key:
        if log:
            log.step("Trying page extraction")
        api_key = await extract_api_key(page)
        if api_key and log:
            log.done()

    if not api_key and navigate_to_api_keys_fn:
        if log:
            log.step("Navigating to API keys page")
        if await navigate_to_api_keys_fn(page):
            api_key = await extract_api_key(page)
        if api_key and log:
            log.done()

    if not api_key and create_api_key_fn:
        if log:
            log.step("Attempting to create new API key")
        if await create_api_key_fn(page):
            api_key = await extract_api_key(page)
        if api_key and log:
            log.done()

    if not api_key:
        if log:
            log.error("Could not obtain API key")
        return None

    if log:
        log.info(f"API key extracted: {api_key[:20]}...")

    if log:
        log.step("Verifying API key")
    verify_result = verify_api_key(api_key)
    if verify_result is not True:
        label = "failed" if verify_result is False else "inconclusive"
        if log:
            log.fail(label)
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
