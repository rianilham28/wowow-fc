"""Email provider — multiple backends, selected via the EMAIL_PROVIDER config.

Public API (unchanged from the old flat module):
    create_email()                     -> tuple[str, str]
    poll_verification_link(email, ...) -> str | None
    block_domain(domain)               -> None

Add a new backend:
    1. Create a class in a new file that inherits from ``EmailBackend`` (base.py).
    2. Import it here and add a branch to ``_build_backend()``.
"""

from src.config import EMAIL_CODE_TIMEOUT, EMAIL_PROVIDER, GMAIL_TOKENS_PATH
from src.email_provider.base import EmailBackend

# ---------------------------------------------------------------------------
# Backend registry + lazy singleton
# ---------------------------------------------------------------------------

_backend: EmailBackend | None = None


def _build_backend() -> EmailBackend:
    """Construct the backend selected by ``EMAIL_PROVIDER``."""
    if EMAIL_PROVIDER == "gmail":
        from src.email_provider.gmail import GmailBackend

        return GmailBackend(tokens_path=GMAIL_TOKENS_PATH)

    # Default / freemail
    from src.email_provider.freemail import FreemailBackend

    return FreemailBackend()


def _get_backend() -> EmailBackend:
    global _backend
    if _backend is None:
        _backend = _build_backend()
    return _backend


# ---------------------------------------------------------------------------
# Public API — thin facades that dispatch to the active backend
# ---------------------------------------------------------------------------


async def create_email() -> tuple[str, str]:
    """Create a new email address using the configured provider.

    Returns (email_address, password).
    """
    return await _get_backend().create_email()


async def poll_verification_link(
    email: str, timeout: int = EMAIL_CODE_TIMEOUT
) -> str | None:
    """Poll the mailbox for a verification link."""
    return await _get_backend().poll_verification_link(email, timeout=timeout)


def block_domain(domain: str) -> None:
    """Mark a domain as blocked so the provider avoids it."""
    _get_backend().block_domain(domain)
