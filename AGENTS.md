# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-01
**Branch:** main

## OVERVIEW

Python 3.12 CLI tool for bulk-creating Firecrawl accounts using REST API + CloakBrowser for anti-bot token generation. Supports Gmail OAuth and Freemail backends.

## STRUCTURE

```
firecrawl-creator/
├── src/                    # All source code (9 files, 1744 lines)
│   ├── main.py             # CLI entry point (`fc` command)
│   ├── config.py           # .env loader + constants
│   ├── creator_rest.py     # LIVE: REST-based registration
│   ├── creator.py          # DEAD: Browser-based registration (unused)
│   ├── email_provider.py   # Gmail + Freemail backends
│   ├── validate.py         # API key extraction + verification
│   ├── upload.py           # Upload keys to MySearch proxy
│   └── log.py              # Structured logging (Rich)
├── profiles/               # Browser profiles (runtime, gitignored)
├── docs/                   # Design docs
├── .env                    # Active config (gitignored)
├── .env.example            # Config template
├── pyproject.toml          # Project config, deps, ruff
└── uv.lock                 # Dependency lockfile
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Run the tool | `fc [count] [--concurrency N] [--proxy URL]` | Entry point: `src.main:main` |
| Change registration flow | `src/creator_rest.py` | **Only use this file** — `creator.py` is dead code |
| Add email provider | `src/email_provider.py` | Gmail/Freemail backends, switch via `EMAIL_PROVIDER` env |
| Modify config | `src/config.py` + `.env` | Custom dotenv parser, not `python-dotenv` |
| Extract/verify API keys | `src/validate.py` | Also handles save + upload trigger |
| Upload to server | `src/upload.py` | POST to MySearch proxy |
| Logging output | `src/log.py` | Rich console, per-account tagging |

## CONVENTIONS

- **Line length**: 100 (not Ruff default 88)
- **Ruff rules**: E, F, I, N, W, UP, B, SIM, ARG (strict)
- **Python**: 3.12 only — use match statements, type params freely
- **Async**: All I/O is async (`asyncio`), sync wrappers where needed
- **HTTP**: `curl_cffi` with `impersonate="chrome"` — NOT `httpx` or `requests`
- **Browser**: `cloakbrowser` for anti-bot token generation only
- **Config**: Custom `.env` parser in `config.py`, module-level constants

## ANTI-PATTERNS (THIS PROJECT)

- **DO NOT use `src/creator.py`** — dead code from old browser-automation approach
- **DO NOT add `httpx` or `requests`** — project uses `curl_cffi` exclusively
- **DO NOT import `upload` at module level** — lazy import inside functions to avoid cycles
- **NEVER commit `.env`** — contains real credentials
- **NEVER commit `profiles/`** — browser cache data
- **NEVER commit `firecrawl_accounts.txt`** — generated account data

## UNIQUE STYLES

- **Monocle token caching**: `creator_rest.py` caches `monocleAssessment` token globally, regenerates after 2 failures
- **Sticky proxy**: Email-based proxy routing via Resin (`PROXY_HOST` config)
- **Verification link extraction**: Multi-pass URL parsing with host+path hints
- **PKCE auth flow**: REST-based verification uses OAuth code exchange (no browser needed)

## COMMANDS

```bash
# Install
uv sync

# Run
fc 10 --concurrency 3 --proxy socks5://user:pass@host:port

# Lint
ruff check .

# Build package
python -m build
```

## NOTES

- `firecrawl_crator.egg-info/` is stale (old project name with typo) — ignore it
- `SIGNUP_ACTION` constant in `creator_rest.py:29` may need updating if Firecrawl changes their Next.js action hash
- Gmail backend requires OAuth tokens in `gmail-tokens.json` (gitignored)
- Freemail backend requires `FREEMAIL_API_URL` + `FREEMAIL_API_TOKEN` in `.env`
