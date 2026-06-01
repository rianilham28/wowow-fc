"""Configuration loader — reads .env into module-level constants."""

import os
from pathlib import Path

PLACEHOLDER_ENV_VALUES: dict[str, list[str]] = {
"FREEMAIL_API_URL": ["https://your-freemail-api.example.com"],
"FREEMAIL_API_TOKEN": ["replace-with-your-freemail-token"],
}


# Custom .env parser instead of python-dotenv because:
# 1. Zero dependencies — one less package to install
# 2. Supports inline comments and quoted values
# 3. Simple enough for this project's needs

def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _get_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def is_placeholder_env_value(name: str, value: str) -> bool:
    normalized = (value or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    known = [i.lower() for i in PLACEHOLDER_ENV_VALUES.get(name, [])]
    if lowered in known:
        return True
    if lowered.startswith("replace-with-"):
        return True
    return lowered in {"example.com", "example.org"}


def validate_config() -> bool:
    missing: list[str] = []
    placeholder: list[str] = []

    if EMAIL_PROVIDER == "gmail":
        if not GMAIL_TOKENS_PATH:
            missing.append("GMAIL_TOKENS_PATH")
        else:
            from pathlib import Path

            path = Path(os.path.expanduser(GMAIL_TOKENS_PATH))
            if not path.exists():
                missing.append(f"GMAIL_TOKENS_PATH (file not found: {path})")
    elif EMAIL_PROVIDER == "freemail":
        if not FREEMAIL_API_URL:
            missing.append("FREEMAIL_API_URL")
        elif is_placeholder_env_value("FREEMAIL_API_URL", FREEMAIL_API_URL):
            placeholder.append("FREEMAIL_API_URL")
        if not FREEMAIL_API_TOKEN:
            missing.append("FREEMAIL_API_TOKEN")
        elif is_placeholder_env_value("FREEMAIL_API_TOKEN", FREEMAIL_API_TOKEN):
            placeholder.append("FREEMAIL_API_TOKEN")
    else:
        print(f"Unknown EMAIL_PROVIDER: {EMAIL_PROVIDER}. Use 'gmail' or 'freemail'.")
        return False

    if missing or placeholder:
        if missing:
            print("Missing required configuration:")
            for k in missing:
                print(f"  - {k}")
        if placeholder:
            print("Detected placeholder values in .env:")
            for k in placeholder:
                print(f"  - {k}")
        return False
    return True


_load_dotenv()

# Email provider selection ("gmail" or "freemail")
EMAIL_PROVIDER: str = _get_str("EMAIL_PROVIDER", "freemail").lower()

# Gmail OAuth tokens
GMAIL_TOKENS_PATH: str = _get_str("GMAIL_TOKENS_PATH", "gmail-tokens.json")

# Freemail (temporary email service)
FREEMAIL_API_URL: str = _get_str("FREEMAIL_API_URL")
FREEMAIL_API_TOKEN: str = _get_str("FREEMAIL_API_TOKEN")

# Proxy
PROXY_URL: str = _get_str("PROXY_URL")

# Resin sticky proxy config
PROXY_HOST: str = _get_str("PROXY_HOST")
PROXY_PORT: str = _get_str("PROXY_PORT", "2260")
PROXY_TOKEN: str = _get_str("PROXY_TOKEN")
PROXY_PLATFORM: str = _get_str("PROXY_PLATFORM", "Default")

# Upload to MySearch proxy
SERVER_URL: str = _get_str("SERVER_URL")
SERVER_ADMIN_PASSWORD: str = _get_str("SERVER_ADMIN_PASSWORD")

# Registration defaults
DEFAULT_COUNT: int = _get_int("DEFAULT_COUNT", 1)
DEFAULT_CONCURRENCY: int = _get_int("DEFAULT_CONCURRENCY", 2)
DEFAULT_DELAY: int = _get_int("DEFAULT_DELAY", 10)

# Email polling
EMAIL_CODE_TIMEOUT: int = _get_int("EMAIL_CODE_TIMEOUT", 30)
EMAIL_POLL_INTERVAL: int = _get_int("EMAIL_POLL_INTERVAL", 2)
# API key verification
API_KEY_TIMEOUT: int = _get_int("API_KEY_TIMEOUT", 20)

# Firecrawl API constants (magic strings from creator_rest.py)
SIGNUP_ACTION: str = "703cbd7d984f74f293927ea3aa6335a018fbca6bf7"
SUPABASE_AUTH_COOKIE: str = "sb-alttmdsdujxrfnakrkyi-auth-token"
SUPABASE_CODE_VERIFIER_COOKIE: str = "sb-alttmdsdujxrfnakrkyi-auth-token-code-verifier"
MCL_SCRIPT_URL: str = (
    "https://mcl.spur.us/d/mcl.js?tk=SMEGdTvQUE9moLnclaZZ76IgFMbJahmglg8xygdJsugIgtjv4Y152CEq6"
    "dTY3SPpRPpHiPFDZjLb0nR5qpYGxhzpjcJVpif5W8PP4FVSv1ePuBe5eU6fQsru0qNz0bU6NaCgZsmU"
    "CQlenaB7d497kVvjNxcMmc4k1pW9zXR3KwS3omYaMGlHzwOQZmVIND0c7mjXNzy9oatHBfYHNuf5CPXf"
    "7XU3ZSYcUwqXFkE54HqZdmk1zXWSeJQAQe3kMrsoNLQ5bOLQNmNT6UyfBqXktVxl9x5Y2gHjt0n2D3M"
    "My47LgZ5x0SYnE85HnvvLRvNA4ZNvD35BIDc4Z5J6JCgsUfSP8ILNH8YK7X6j7T9xtATukEYLpr4lFu"
    "fXyPcIfKjSLRsMEMXVHydiHIXINUuYHvsIA9xQYIrbf1rpuf"
)
