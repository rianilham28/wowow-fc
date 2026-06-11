# firecrawl-creator

Bulk-create Firecrawl accounts via REST API with CloakBrowser anti-bot token generation.

> This project is shared on [LINUX DO](https://linux.do) — a friendly Chinese tech community.


## Features

- **REST-based registration** — no browser automation for the signup flow itself; uses direct HTTP requests with `curl_cffi` (Chrome impersonation)
- **CloakBrowser token generation** — spawns a stealth browser only to produce the `monocleAssessment` anti-bot token, with aggressive caching (reused until 2 consecutive failures)
- **Gmail and Freemail backends** — choose between Gmail OAuth for real mailboxes or a Freemail REST API for disposable addresses
- **Concurrent execution** — register multiple accounts in parallel with configurable concurrency and delay
- **Automatic verification** — polls for the confirmation link, completes PKCE-based email verification, and extracts the API key
- **Server upload** — verified keys are automatically pushed to a MySearch proxy server

## Prerequisites

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) package manager

## Installation

```bash
git clone <repo-url> && cd firecrawl-creator
uv sync
```

The `fc` command becomes available after installation.

## Configuration

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `EMAIL_PROVIDER` | `gmail` or `freemail` | `freemail` |
| `GMAIL_TOKENS_PATH` | Path to Gmail OAuth tokens JSON | `gmail-tokens.json` |
| `FREEMAIL_API_URL` | Freemail service base URL | — |
| `FREEMAIL_API_TOKEN` | Freemail API bearer token | — |
| `PROXY_URL` | Proxy for CloakBrowser (`protocol://user:pass@host:port`) | — |
| `DEFAULT_COUNT` | Accounts to create per run | `1` |
| `DEFAULT_CONCURRENCY` | Max parallel sessions | `2` |
| `DEFAULT_DELAY` | Seconds between registrations | `10` |
| `EMAIL_CODE_TIMEOUT` | Max seconds to wait for verification email | `30` |
| `EMAIL_POLL_INTERVAL` | Seconds between email inbox checks | `2` |
| `API_KEY_TIMEOUT` | Seconds to wait for API key to become active | `20` |
| `SERVER_URL` | MySearch proxy upload endpoint | — |
| `SERVER_ADMIN_PASSWORD` | Admin password for the upload server | — |

See `.env.example` for the full list including Resin sticky proxy settings.

## Usage

Basic, create one account:

```bash
fc
```

Create 10 accounts with 3 concurrent sessions:

```bash
fc 10 --concurrency 3
```

Use a SOCKS5 proxy:

```bash
fc 5 --proxy socks5://user:pass@host:port
```

### CLI reference

```
fc [count] [--concurrency N] [--proxy URL]
```

| Argument | Description |
|---|---|
| `count` | Number of accounts to create (overrides `DEFAULT_COUNT`) |
| `--concurrency` | Max parallel registrations (overrides `DEFAULT_CONCURRENCY`) |
| `--proxy` | Proxy URL for CloakBrowser (overrides `PROXY_URL`) |

## How it works

1. **Email creation** — allocates a new address via the configured backend (Gmail OAuth or Freemail API)
2. **Token generation** — CloakBrowser launches through the proxy and produces a `monocleAssessment` anti-bot token (cached and reused across accounts)
3. **Signup** — sends a REST POST to Firecrawl's signup endpoint with email, password, and the assessment token
4. **Verification** — polls the email inbox for the confirmation link, then completes PKCE-based email verification via REST
5. **Key extraction** — fetches the API key from Firecrawl's `/api/user/team` endpoint and verifies it works
6. **Save and upload** — appends `email,password,api_key` to `firecrawl_accounts.txt` and optionally uploads to the MySearch proxy server

## Project structure

```
src/
  main.py             CLI entry point, argument parsing, async orchestration
  config.py           .env loader, module-level constants, config validation
  creator_rest.py     REST-based registration flow (signup, verification, key fetch)
  email_provider.py   Gmail OAuth and Freemail backends, verification link polling
  validate.py         API key extraction, live verification, account file persistence
  upload.py           Upload verified keys to MySearch proxy server
  log.py              Structured console output using Rich
```

## Output

Successful accounts are appended to `firecrawl_accounts.txt` in the project root:

```
email@example.com,securepassword,fc-abc123def456
```
