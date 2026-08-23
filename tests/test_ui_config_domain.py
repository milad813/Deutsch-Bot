"""Characterization tests for ui text helpers, config parsers, domain.user."""

import pytest

import config
from domain.user import level_from_xp
from ui import (
    _chunk_html_text,
    _short_label,
    esc,
    progress_bar,
    sanitize_html,
    strip_html,
)


# ─── ui ──────────────────────────────────────────────────────────


def test_esc_handles_none_and_html():
    assert esc(None) == ""
    assert esc("<b>&") == "&lt;b&gt;&amp;"
    assert esc(5) == "5"


def test_sanitize_html_keeps_only_allowed_tags():
    dirty = "<b>hi</b><script>alert(1)</script><img src=x>"
    clean = sanitize_html(dirty)
    assert "<b>hi</b>" in clean
    assert "script" not in clean.lower()
    assert "<img" not in clean


def test_strip_html_unescapes_entities():
    assert strip_html("<b>a &amp; b</b>") == "a & b"


def test_chunk_html_text_splits_long_payloads():
    text = "word " * 2000  # ~10 KB utf-8
    chunks = _chunk_html_text(text)
    assert len(chunks) >= 2
    assert all(len(c.encode("utf-8")) <= 3900 for c in chunks)
    assert "".join(chunks).split() == text.split()


def test_progress_bar():
    assert progress_bar(0, 10) == "░" * 10
    assert progress_bar(5, 10, width=10) == "█" * 5 + "░" * 5
    assert progress_bar(10, 10) == "█" * 10
    assert progress_bar(3, 0) == "░" * 10


def test_short_label():
    assert _short_label("abc", 5) == "abc"
    out = _short_label("abcdef", 5)
    assert out == "ab..." and len(out) == 5


# ─── config ──────────────────────────────────────────────────────


def test_get_env_prefers_os_environ(monkeypatch):
    monkeypatch.setenv("DEUTSCH_BOT_TEST_VAR", "from-env")
    assert config.get_env("DEUTSCH_BOT_TEST_VAR", "fallback") == "from-env"
    monkeypatch.delenv("DEUTSCH_BOT_TEST_VAR")
    assert config.get_env("DEUTSCH_BOT_TEST_VAR", "fallback") == "fallback"


def test_get_bool_parsing(monkeypatch):
    for truthy in ("1", "true", "YES", "on"):
        monkeypatch.setenv("X_FLAG", truthy)
        assert config._get_bool("X_FLAG", False) is True
    monkeypatch.setenv("X_FLAG", "0")
    assert config._get_bool("X_FLAG", True) is False


def test_validate_config_raises_on_missing_token(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "ADMIN_USER_ID", 0)
    monkeypatch.setattr(config, "ALLOW_PUBLIC_ACCESS", False)
    with pytest.raises(RuntimeError) as exc:
        config.validate_config()
    assert "TELEGRAM_BOT_TOKEN" in str(exc.value)


def test_public_access_allows_missing_admin(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(config, "ADMIN_USER_ID", 0)
    monkeypatch.setattr(config, "ALLOW_PUBLIC_ACCESS", True)
    config.validate_config()  # must not raise


def test_is_authorized_user_matrix(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PUBLIC_ACCESS", True)
    assert config.is_authorized_user(999999)
    monkeypatch.setattr(config, "ALLOW_PUBLIC_ACCESS", False)
    monkeypatch.setattr(config, "ADMIN_USER_ID", 7)
    assert config.is_authorized_user(7)
    assert not config.is_authorized_user(8)


# ─── domain.user ─────────────────────────────────────────────────


def test_level_from_xp():
    assert level_from_xp(0) == (1, 0, 100)
    assert level_from_xp(99) == (1, 99, 100)
    assert level_from_xp(100) == (2, 0, 100)
    assert level_from_xp(250) == (3, 50, 100)


def test_level_from_xp_is_defensive():
    assert level_from_xp(-50) == level_from_xp(0)
    assert level_from_xp(None) == level_from_xp(0)
