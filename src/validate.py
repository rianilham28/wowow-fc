"""API key extraction and live verification against Firecrawl API."""

import asyncio
import os
import threading
from pathlib import Path

from curl_cffi.requests.errors import RequestsError

from src.config import API_KEY_TIMEOUT, MAX_RETRIES
from src.log import Log
from src.session import default_manager as session

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
_SAVE_FILE = os.path.join(_PROJECT_ROOT, "firecrawl_accounts.txt")
_SAVE_LOCK = threading.Lock()

TEAM_API_URL = "https://www.firecrawl.dev/api/user/team"


def save_account(email: str, password: str, api_key: str) -> None:
    with _SAVE_LOCK, open(_SAVE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{email},{password},{api_key}\n")


async def verify_api_key(api_key: str, log: Log | None = None) -> bool | None:
    """Verify an API key by making a test scrape request."""
    transient_errors = (RequestsError, OSError)
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await session.get_async().post(
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
            if attempt < MAX_RETRIES:
                if log:
                    log.info(f"Retry ({attempt}/{MAX_RETRIES}): {exc}")
                await asyncio.sleep(attempt)
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
