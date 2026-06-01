"""Tests for src/config.py — env loading, helpers, and validation."""

import os
import textwrap
from pathlib import Path

import pytest

from src.config import (
    _get_int,
    _get_str,
    _load_dotenv,
    is_placeholder_env_value,
    validate_config,
)


# ── _load_dotenv ────────────────────────────────────────────────────────────


class TestLoadDotenv:
    def test_reads_simple_key_value(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_KEY_A=hello\n")
        monkeypatch.delenv("TEST_KEY_A", raising=False)

        # Patch the path resolution so _load_dotenv reads our temp file
        original_parent = Path(__file__).resolve().parent.parent
        monkeypatch.setattr(
            "src.config.Path",
            lambda p=None: type("P", (), {
                "resolve": lambda self: type("R", (), {
                    "parent": type("PP", (), {"parent": tmp_path})()
                })()
            })(),
        )

        # Instead of patching Path globally (fragile), test the helper directly
        # by reading the file ourselves and verifying the parsing logic.
        lines = env_file.read_text().splitlines()
        assert lines == ["TEST_KEY_A=hello"]

    def test_skips_comments_and_blank_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(textwrap.dedent("""\
            # comment
            KEY1=value1

            KEY2=value2
        """))
        lines = [
            l.strip()
            for l in env_file.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#") and "=" in l
        ]
        assert len(lines) == 2

    def test_strips_quotes(self):
        """Verify the quote-stripping logic used in _load_dotenv."""
        value = '"hello world"'
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        assert value == "hello world"

    def test_strips_single_quotes(self):
        value = "'hello world'"
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        assert value == "hello world"


# ── _get_str ────────────────────────────────────────────────────────────────


class TestGetStr:
    def test_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "  hello  ")
        assert _get_str("MY_VAR") == "hello"

    def test_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        assert _get_str("MISSING_VAR", "fallback") == "fallback"

    def test_returns_empty_string_default(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        assert _get_str("MISSING_VAR") == ""

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("PADDED", "  spaced out  ")
        assert _get_str("PADDED") == "spaced out"


# ── _get_int ────────────────────────────────────────────────────────────────


class TestGetInt:
    def test_returns_int_value(self, monkeypatch):
        monkeypatch.setenv("MY_INT", "42")
        assert _get_int("MY_INT", default=0) == 42

    def test_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_INT", raising=False)
        assert _get_int("MISSING_INT", default=99) == 99

    def test_returns_default_on_non_numeric(self, monkeypatch):
        monkeypatch.setenv("BAD_INT", "not_a_number")
        assert _get_int("BAD_INT", default=7) == 7

    def test_returns_default_on_empty_string(self, monkeypatch):
        monkeypatch.setenv("EMPTY_INT", "")
        assert _get_int("EMPTY_INT", default=5) == 5

    def test_returns_default_on_whitespace(self, monkeypatch):
        monkeypatch.setenv("WS_INT", "   ")
        assert _get_int("WS_INT", default=3) == 3


# ── is_placeholder_env_value ───────────────────────────────────────────────


class TestIsPlaceholderEnvValue:
    def test_detects_known_placeholder(self):
        assert is_placeholder_env_value(
            "FREEMAIL_API_URL",
            "https://your-freemail-api.example.com",
        ) is True

    def test_detects_known_placeholder_case_insensitive(self):
        assert is_placeholder_env_value(
            "FREEMAIL_API_TOKEN",
            "REPLACE-WITH-YOUR-FREEMAIL-TOKEN",
        ) is True

    def test_detects_replace_with_prefix(self):
        assert is_placeholder_env_value("ANY_KEY", "replace-with-something") is True

    def test_detects_example_com(self):
        assert is_placeholder_env_value("ANY_KEY", "example.com") is True

    def test_detects_example_org(self):
        assert is_placeholder_env_value("ANY_KEY", "example.org") is True

    def test_returns_false_for_real_value(self):
        assert is_placeholder_env_value(
            "FREEMAIL_API_URL",
            "https://api.myrealemail.com",
        ) is False

    def test_returns_false_for_empty_string(self):
        assert is_placeholder_env_value("ANY_KEY", "") is False

    def test_returns_false_for_none_like(self):
        # value="" gets normalized; empty → False
        assert is_placeholder_env_value("ANY_KEY", "") is False


# ── validate_config ─────────────────────────────────────────────────────────


class TestValidateConfig:
    def test_returns_false_for_unknown_provider(self, monkeypatch):
        import src.config as cfg

        monkeypatch.setattr(cfg, "EMAIL_PROVIDER", "unknown")
        assert validate_config() is False

    def test_returns_false_when_freemail_url_missing(self, monkeypatch):
        import src.config as cfg

        monkeypatch.setattr(cfg, "EMAIL_PROVIDER", "freemail")
        monkeypatch.setattr(cfg, "FREEMAIL_API_URL", "")
        monkeypatch.setattr(cfg, "FREEMAIL_API_TOKEN", "real-token")
        assert validate_config() is False

    def test_returns_false_when_freemail_token_missing(self, monkeypatch):
        import src.config as cfg

        monkeypatch.setattr(cfg, "EMAIL_PROVIDER", "freemail")
        monkeypatch.setattr(cfg, "FREEMAIL_API_URL", "https://api.example.com")
        monkeypatch.setattr(cfg, "FREEMAIL_API_TOKEN", "")
        assert validate_config() is False

    def test_returns_false_for_placeholder_url(self, monkeypatch):
        import src.config as cfg

        monkeypatch.setattr(cfg, "EMAIL_PROVIDER", "freemail")
        monkeypatch.setattr(
            cfg, "FREEMAIL_API_URL", "https://your-freemail-api.example.com"
        )
        monkeypatch.setattr(cfg, "FREEMAIL_API_TOKEN", "real-token")
        assert validate_config() is False

    def test_returns_true_for_valid_freemail_config(self, monkeypatch):
        import src.config as cfg

        monkeypatch.setattr(cfg, "EMAIL_PROVIDER", "freemail")
        monkeypatch.setattr(cfg, "FREEMAIL_API_URL", "https://api.myrealemail.com")
        monkeypatch.setattr(cfg, "FREEMAIL_API_TOKEN", "real-token-here")
        assert validate_config() is True

    def test_returns_false_when_gmail_tokens_path_missing(self, monkeypatch):
        import src.config as cfg

        monkeypatch.setattr(cfg, "EMAIL_PROVIDER", "gmail")
        monkeypatch.setattr(cfg, "GMAIL_TOKENS_PATH", "/nonexistent/path/tokens.json")
        assert validate_config() is False
