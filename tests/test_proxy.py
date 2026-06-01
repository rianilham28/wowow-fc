"""Tests for src/proxy.py — sticky proxy URL building."""

import src.proxy as proxy_mod
from src.proxy import build_sticky_proxy


class TestBuildStickyProxy:
    def test_returns_none_when_host_empty(self, monkeypatch):
        monkeypatch.setattr(proxy_mod, "PROXY_HOST", "")
        assert build_sticky_proxy("user@example.com") is None

    def test_builds_url_with_token(self, monkeypatch):
        monkeypatch.setattr(proxy_mod, "PROXY_HOST", "proxy.resin.io")
        monkeypatch.setattr(proxy_mod, "PROXY_PORT", "2260")
        monkeypatch.setattr(proxy_mod, "PROXY_TOKEN", "mytoken123")
        monkeypatch.setattr(proxy_mod, "PROXY_PLATFORM", "US")

        result = build_sticky_proxy("alice@example.com")
        assert result == "http://US.alice:mytoken123@proxy.resin.io:2260"

    def test_builds_url_without_token(self, monkeypatch):
        monkeypatch.setattr(proxy_mod, "PROXY_HOST", "proxy.resin.io")
        monkeypatch.setattr(proxy_mod, "PROXY_PORT", "2260")
        monkeypatch.setattr(proxy_mod, "PROXY_TOKEN", "")
        monkeypatch.setattr(proxy_mod, "PROXY_PLATFORM", "US")

        result = build_sticky_proxy("bob@example.com")
        assert result == "http://US.bob@proxy.resin.io:2260"

    def test_uses_email_local_part_as_account(self, monkeypatch):
        monkeypatch.setattr(proxy_mod, "PROXY_HOST", "proxy.resin.io")
        monkeypatch.setattr(proxy_mod, "PROXY_PORT", "2260")
        monkeypatch.setattr(proxy_mod, "PROXY_TOKEN", "")
        monkeypatch.setattr(proxy_mod, "PROXY_PLATFORM", "Default")

        result = build_sticky_proxy("longuser@example.com")
        assert "longuser" in result
        assert "Default.longuser@" in result

    def test_defaults_platform_to_default(self, monkeypatch):
        monkeypatch.setattr(proxy_mod, "PROXY_HOST", "proxy.resin.io")
        monkeypatch.setattr(proxy_mod, "PROXY_PORT", "2260")
        monkeypatch.setattr(proxy_mod, "PROXY_TOKEN", "")
        monkeypatch.setattr(proxy_mod, "PROXY_PLATFORM", "")

        result = build_sticky_proxy("u@example.com")
        assert "Default.u@" in result

    def test_custom_port(self, monkeypatch):
        monkeypatch.setattr(proxy_mod, "PROXY_HOST", "proxy.resin.io")
        monkeypatch.setattr(proxy_mod, "PROXY_PORT", "9999")
        monkeypatch.setattr(proxy_mod, "PROXY_TOKEN", "")
        monkeypatch.setattr(proxy_mod, "PROXY_PLATFORM", "US")

        result = build_sticky_proxy("u@example.com")
        assert result.endswith(":9999")
