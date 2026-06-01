"""Tests for src/email_provider.py — pure helper functions."""

import re

from src.email_provider import (
    _extract_verification_link_from_content,
    _is_verification,
    _password,
    rand_str,
)


# ── rand_str ────────────────────────────────────────────────────────────────


class TestRandStr:
    def test_default_length(self):
        result = rand_str()
        assert len(result) == 8

    def test_custom_length(self):
        result = rand_str(16)
        assert len(result) == 16

    def test_length_one(self):
        result = rand_str(1)
        assert len(result) == 1

    def test_contains_only_allowed_chars(self):
        result = rand_str(100)
        assert re.fullmatch(r"[a-z0-9]+", result)

    def test_zero_length(self):
        result = rand_str(0)
        assert result == ""


# ── _password ───────────────────────────────────────────────────────────────


class TestPassword:
    def test_starts_with_fc_prefix(self):
        pw = _password()
        assert pw.startswith("Fc")

    def test_ends_with_aA(self):
        pw = _password()
        assert pw.endswith("!aA")

    def test_minimum_length(self):
        pw = _password()
        # Fc + 6 chars + 3 digits + !aA = 14
        assert len(pw) >= 14

    def test_contains_digits(self):
        pw = _password()
        # The middle section should have digits from randint(100, 999)
        digits = re.findall(r"\d+", pw)
        assert len(digits) >= 1

    def test_multiple_calls_differ(self):
        """Random passwords should (almost certainly) not be identical."""
        passwords = {_password() for _ in range(20)}
        assert len(passwords) > 1


# ── _is_verification ────────────────────────────────────────────────────────


class TestIsVerification:
    def test_matches_firecrawl_verify_path(self):
        url = "https://www.firecrawl.dev/verify?token=abc123"
        assert _is_verification(url) is True

    def test_matches_firecrawl_confirm_path(self):
        url = "https://www.firecrawl.dev/confirm-email?code=xyz"
        assert _is_verification(url) is True

    def test_matches_clerk_signin(self):
        url = "https://clerk.firecrawl.dev/signin?token=abc"
        assert _is_verification(url) is True

    def test_rejects_unrelated_url(self):
        url = "https://example.com/some-page"
        assert _is_verification(url) is False

    def test_rejects_image_url(self):
        """Images are filtered separately, but _is_verification checks path+host."""
        url = "https://example.com/image.png"
        assert _is_verification(url) is False

    def test_requires_host_hint(self):
        """Path has 'verify' but host has no firecrawl/clerk → False."""
        url = "https://random-site.com/verify?token=abc"
        assert _is_verification(url) is False

    def test_requires_path_hint(self):
        """Host has firecrawl but path has no verify/confirm → False."""
        url = "https://www.firecrawl.dev/dashboard"
        assert _is_verification(url) is False


# ── _extract_verification_link_from_content ─────────────────────────────────


class TestExtractVerificationLink:
    def test_extracts_link_from_html_content(self):
        html = (
            '<a href="https://www.firecrawl.dev/verify?token=abc123">'
            "Click to verify</a>"
        )
        result = _extract_verification_link_from_content(
            subject="Verify your email",
            sender="noreply@firecrawl.dev",
            content=html,
        )
        assert result is not None
        assert "firecrawl.dev/verify" in result

    def test_returns_none_for_no_links(self):
        result = _extract_verification_link_from_content(
            subject="Hello",
            sender="test@example.com",
            content="No links here at all",
        )
        assert result is None

    def test_ignores_image_urls(self):
        html = (
            '<img src="https://www.firecrawl.dev/logo.png" />'
            '<a href="https://www.firecrawl.dev/verify?token=abc">Verify</a>'
        )
        result = _extract_verification_link_from_content(
            subject="Verify",
            sender="noreply@firecrawl.dev",
            content=html,
        )
        assert result is not None
        assert "verify" in result
        assert ".png" not in result

    def test_second_pass_matches_with_msg_hints(self):
        """When no strict host+path match, falls back to path-only if msg is verification-related."""
        content = "Click https://clerk.example.com/callback?code=xyz to sign in"
        result = _extract_verification_link_from_content(
            subject="Sign in to Firecrawl",
            sender="noreply@firecrawl.dev",
            content=content,
        )
        assert result is not None
        assert "callback" in result

    def test_returns_none_for_unrelated_message(self):
        content = "Visit https://example.com/page for details"
        result = _extract_verification_link_from_content(
            subject="Newsletter",
            sender="marketing@example.com",
            content=content,
        )
        assert result is None

    def test_prefers_first_matching_link(self):
        html = (
            '<a href="https://www.firecrawl.dev/verify?token=first">First</a> '
            '<a href="https://www.firecrawl.dev/verify?token=second">Second</a>'
        )
        result = _extract_verification_link_from_content(
            subject="Verify",
            sender="noreply@firecrawl.dev",
            content=html,
        )
        assert "first" in result
