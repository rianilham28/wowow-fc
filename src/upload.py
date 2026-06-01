"""Upload verified API keys to MySearch proxy."""

from curl_cffi.requests import Session

from src.config import SERVER_ADMIN_PASSWORD, SERVER_URL
from src.log import Log


def upload_key(email: str, api_key: str, log: Log | None = None) -> bool:
    if not SERVER_URL or not SERVER_ADMIN_PASSWORD:
        return False

    if log:
        log.step("Uploading to server")
    try:
        resp = Session().post(
            f"{SERVER_URL}/api/keys",
            json={"key": api_key, "email": email, "service": "firecrawl"},
            headers={"Authorization": f"Bearer {SERVER_ADMIN_PASSWORD}"},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            if log:
                log.done()
            return True
        if log:
            log.fail(f"{resp.status_code}")
        return False
    except Exception as exc:
        if log:
            log.fail(str(exc))
        return False
