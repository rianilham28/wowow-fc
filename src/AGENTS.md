# src/ — Source Code

## OVERVIEW

All application code. 9 Python files, 1744 lines total. Flat structure (no subpackages).

## WHERE TO LOOK

| Task | File | Key Functions |
|------|------|---------------|
| CLI args / orchestration | `main.py` | `main()`, `main_async()`, `run()`, `register_one()` |
| Environment config | `config.py` | `validate_config()`, module-level constants |
| REST registration | `creator_rest.py` | `create_account_rest()`, `get_monocle_assessment()`, `signup_via_rest()` |
| Browser registration | `creator.py` | ⚠️ **DEAD CODE** — do not use |
| Email creation/polling | `email_provider.py` | `create_email()`, `poll_verification_link()`, `GmailBackend` |
| Key extraction | `validate.py` | `extract_and_verify_key()`, `verify_api_key()`, `save_account()` |
| Server upload | `upload.py` | `upload_key()` |
| Console output | `log.py` | `Log` class (step/done/fail/info/ok/error/detail) |

## MODULE DEPENDENCY GRAPH

```
main.py ──► config, email_provider, log, creator_rest
creator_rest.py ──► config, email_provider, log, validate, upload (lazy)
creator.py ──► config, email_provider, log, validate (DEAD)
validate.py ──► config, log, upload (lazy)
upload.py ──► config, log
email_provider.py ──► config
log.py ──► rich
config.py ──► os, pathlib
```

## CONVENTIONS

- **Lazy imports**: `upload.py` is imported inside function bodies (lines 184, 353) to avoid circular deps
- **Global state**: `_CLI_PROXY`, `_CLI_COUNT`, `_CLI_CONCURRENCY` in `main.py`; `_cached_assessment` in `creator_rest.py`; `_gmail_backend` in `email_provider.py`
- **Error handling**: `contextlib.suppress(Exception)` for cleanup; `try/except` with logging
- **Type hints**: Python 3.12 style (`str | None`, `list[str]`)

## ANTI-PATTERNS

- **DO NOT** add module-level imports of `upload` — will cause circular import
- **DO NOT** use `creator.py` — it's dead code, `main.py` imports `creator_rest`
- **NEVER** suppress type errors with `as any` or `@ts-ignore` (N/A for Python, but same principle)
