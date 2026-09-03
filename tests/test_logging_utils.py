"""Tests for :mod:`core.logging_utils`.

We verify four things:

1. :class:`JsonFormatter` emits valid, single-line JSON that always
   includes ``timestamp`` / ``level`` / ``logger`` / ``message``.
2. :func:`log_event` propagates the event name and arbitrary extra
   fields into both the JSON payload and the text-formatter suffix.
3. Common secret-looking field names are always redacted, never
   echoed -- even when a caller accidentally passes a real token.
4. Prompt-shaped strings are truncated so a debug-level dump of a
   4 KB LLM prompt never blows up a log line.

These tests run in isolation: they install a fresh logger handler
on a private logger to avoid polluting the root logger.
"""

from __future__ import annotations

import io
import json
import logging
import re

import pytest

from core.logging_utils import (
    JsonFormatter,
    TextWithExtrasFormatter,
    log_event,
)


@pytest.fixture
def captured_json() -> logging.Handler:
    """Return a handler that writes a JSON line to a private buffer.

    The handler is attached to a private ``NullHandler``-rooted
    logger (``"tests.logging_utils.json"``) so each test can read
    exactly one log line without contending with the real bot log
    config.
    """
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("tests.logging_utils.json")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler._buf = buf  # type: ignore[attr-defined]
    return handler


@pytest.fixture
def captured_text() -> logging.Handler:
    """Same as :func:`captured_json` but for the text formatter."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(TextWithExtrasFormatter())
    logger = logging.getLogger("tests.logging_utils.text")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler._buf = buf  # type: ignore[attr-defined]
    return handler


def test_json_formatter_outputs_valid_json(captured_json):
    """A simple log call must round-trip through ``json.loads``."""
    logger = logging.getLogger("tests.logging_utils.json")
    log_event(logger, logging.INFO, "test_event", foo=1, bar="two")
    raw = captured_json._buf.getvalue().strip()  # type: ignore[attr-defined]
    # Must be exactly one line of valid JSON.
    assert "\n" not in raw
    data = json.loads(raw)
    assert isinstance(data, dict)
    assert data["foo"] == 1
    assert data["bar"] == "two"


def test_json_formatter_contains_required_fields(captured_json):
    """The top-level keys must always be present."""
    logger = logging.getLogger("tests.logging_utils.json")
    log_event(logger, logging.WARNING, "sample")
    data = json.loads(captured_json._buf.getvalue().strip())  # type: ignore[attr-defined]
    for key in ("timestamp", "level", "logger", "message", "event"):
        assert key in data, f"missing key: {key}"
    assert data["level"] == "WARNING"
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", data["timestamp"]
    )
    assert data["event"] == "sample"


def test_log_event_includes_event_name(captured_json):
    """``event=`` appears in both the text suffix and the JSON payload."""
    logger = logging.getLogger("tests.logging_utils.json")
    log_event(
        logger, logging.INFO, "story_generation_failed", user_id=1
    )
    data = json.loads(captured_json._buf.getvalue().strip())  # type: ignore[attr-defined]
    assert data["event"] == "story_generation_failed"
    assert data["user_id"] == 1
    text = data["message"]
    assert "event=story_generation_failed" in text
    assert "user_id=1" in text


def test_log_event_extra_fields_appear(captured_json):
    """Arbitrary keyword fields must show up in the JSON payload."""
    logger = logging.getLogger("tests.logging_utils.json")
    log_event(
        logger,
        logging.INFO,
        "story_generation_started",
        user_id=42,
        lesson_id=7,
        chat_id=999,
    )
    data = json.loads(captured_json._buf.getvalue().strip())  # type: ignore[attr-defined]
    assert data["user_id"] == 42
    assert data["lesson_id"] == 7
    assert data["chat_id"] == 999
    assert data["event"] == "story_generation_started"


def test_log_event_truncates_prompt_fields(captured_json):
    """Full LLM prompts must be truncated, not echoed verbatim."""
    logger = logging.getLogger("tests.logging_utils.json")
    long_prompt = "X" * 5000
    log_event(
        logger,
        logging.DEBUG,
        "llm_debug",
        full_prompt=long_prompt,
        short=42,
    )
    data = json.loads(captured_json._buf.getvalue().strip())  # type: ignore[attr-defined]
    # The original 5 KB blob must NOT appear in the JSON output.
    assert long_prompt not in captured_json._buf.getvalue()  # type: ignore[attr-defined]
    # The truncated form should still be present (and much shorter).
    truncated = data["full_prompt"]
    assert isinstance(truncated, str)
    assert len(truncated) < 500
    # Unrelated fields are untouched.
    assert data["short"] == 42


# --- Secret redaction ----------------------------------------------


@pytest.mark.parametrize(
    "secret_key",
    [
        "telegram_bot_token",
        "TELEGRAM_BOT_TOKEN",
        "groq_api_key",
        "GROQ_API_KEY",
        "api_key",
        "token",
        "password",
        "secret",
        "authorization",
    ],
)
def test_secrets_are_redacted_in_json(captured_json, secret_key):
    """Common secret keys must never echo the value, even when set."""
    logger = logging.getLogger("tests.logging_utils.json")
    log_event(
        logger,
        logging.INFO,
        "test_event",
        **{secret_key: "sk-SECRET-VALUE-DO-NOT-LEAK"},
    )
    raw = captured_json._buf.getvalue()  # type: ignore[attr-defined]
    assert "sk-SECRET-VALUE-DO-NOT-LEAK" not in raw
    assert "***REDACTED***" in raw


def test_nested_secrets_are_redacted(captured_json):
    """Secrets nested inside a list/dict are also redacted."""
    logger = logging.getLogger("tests.logging_utils.json")
    log_event(
        logger,
        logging.INFO,
        "test_event",
        messages=[{"role": "user", "api_key": "sk-INNER-SECRET"}],
    )
    raw = captured_json._buf.getvalue()  # type: ignore[attr-defined]
    assert "sk-INNER-SECRET" not in raw


def test_user_messages_are_redacted(captured_json):
    """User-supplied content fields must be redacted, not echoed."""
    logger = logging.getLogger("tests.logging_utils.json")
    log_event(
        logger,
        logging.INFO,
        "test_event",
        user_message="Hello, my number is 09123456789",
        message_text="another PII string",
    )
    raw = captured_json._buf.getvalue()  # type: ignore[attr-defined]
    assert "09123456789" not in raw
    assert "Hello" not in raw
    assert "another PII string" not in raw
    assert raw.count("***REDACTED***") >= 2


def test_logging_never_logs_token_at_any_level(captured_json):
    """Even DEBUG-level log calls must not leak the token."""
    logger = logging.getLogger("tests.logging_utils.json")
    log_event(
        logger,
        logging.DEBUG,
        "debug_dump",
        groq_api_key="gsk-LIVE-KEY",
        api_key="another-secret",
    )
    raw = captured_json._buf.getvalue()  # type: ignore[attr-defined]
    assert "gsk-LIVE-KEY" not in raw
    assert "another-secret" not in raw


# --- Text formatter -----------------------------------------------


def test_text_formatter_includes_event_name(captured_text):
    """The text suffix must include the event name and key=value pairs."""
    logger = logging.getLogger("tests.logging_utils.text")
    log_event(
        logger,
        logging.INFO,
        "story_generation_started",
        user_id=42,
        lesson_id=7,
    )
    raw = captured_text._buf.getvalue().strip()  # type: ignore[attr-defined]
    assert "event=story_generation_started" in raw
    assert "user_id=42" in raw
    assert "lesson_id=7" in raw


def test_text_formatter_redacts_secrets(captured_text):
    """The text branch must scrub secrets too, not just JSON."""
    logger = logging.getLogger("tests.logging_utils.text")
    log_event(
        logger,
        logging.INFO,
        "test_event",
        telegram_bot_token="123456:ABCDE-SECRET",
    )
    raw = captured_text._buf.getvalue()  # type: ignore[attr-defined]
    assert "ABCDE-SECRET" not in raw
    assert "***REDACTED***" in raw


def test_text_formatter_omits_suffix_for_plain_logs(captured_text):
    """A plain ``logger.info("hi")`` must NOT get a ``key=value`` suffix.

    This keeps existing log lines (which never went through
    ``log_event``) byte-identical to the historical output.
    """
    logger = logging.getLogger("tests.logging_utils.text")
    logger.info("hi there")
    raw = captured_text._buf.getvalue().strip()  # type: ignore[attr-defined]
    # The standard prefix and the message must both be there.
    assert "hi there" in raw
    # And no extra suffix should have been added.
    assert raw.endswith("hi there"), repr(raw)


# --- setup_logging integration ------------------------------------


def test_setup_logging_text_uses_text_formatter(monkeypatch):
    """``LOG_FORMAT=text`` (default) installs the text formatter."""
    import config

    monkeypatch.setattr(config, "LOG_FORMAT", "text", raising=False)
    monkeypatch.setattr(config, "LOG_LEVEL", "INFO", raising=False)
    config.setup_logging()
    root = logging.getLogger()
    assert root.handlers, "setup_logging must install a root handler"
    handler = root.handlers[0]
    assert isinstance(handler.formatter, TextWithExtrasFormatter)


def test_setup_logging_json_uses_json_formatter(monkeypatch):
    """``LOG_FORMAT=json`` installs the JSON formatter."""
    import config

    monkeypatch.setattr(config, "LOG_FORMAT", "json", raising=False)
    monkeypatch.setattr(config, "LOG_LEVEL", "INFO", raising=False)
    config.setup_logging()
    root = logging.getLogger()
    handler = root.handlers[0]
    assert isinstance(handler.formatter, JsonFormatter)


def test_setup_logging_invalid_level_falls_back_to_info(monkeypatch, caplog):
    """A bogus ``LOG_LEVEL`` must not crash; it must warn and use INFO."""
    import config

    monkeypatch.setattr(config, "LOG_FORMAT", "text", raising=False)
    monkeypatch.setattr(config, "LOG_LEVEL", "BOGUS", raising=False)
    with caplog.at_level(logging.WARNING):
        config.setup_logging()
    assert any(
        "LOG_LEVEL" in rec.message for rec in caplog.records
    ), "expected a warning about the unknown LOG_LEVEL"
    root = logging.getLogger()
    assert root.level == logging.INFO


def test_setup_logging_level_respected(monkeypatch):
    """``LOG_LEVEL=DEBUG`` actually lowers the root level."""
    import config

    monkeypatch.setattr(config, "LOG_FORMAT", "text", raising=False)
    monkeypatch.setattr(config, "LOG_LEVEL", "DEBUG", raising=False)
    config.setup_logging()
    root = logging.getLogger()
    assert root.level == logging.DEBUG


# --- Edge cases ----------------------------------------------------


def test_log_event_rejects_empty_event_name(captured_json):
    """A missing or empty event name must be rejected, not silently swallowed."""
    logger = logging.getLogger("tests.logging_utils.json")
    with pytest.raises(ValueError):
        log_event(logger, logging.INFO, "")
    with pytest.raises(ValueError):
        log_event(logger, logging.INFO, None)  # type: ignore[arg-type]


def test_json_formatter_handles_unserializable(captured_json):
    """An unserializable ``extra`` value must not crash the formatter."""
    logger = logging.getLogger("tests.logging_utils.json")
    # A ``set`` is not JSON-serializable by default.
    log_event(
        logger,
        logging.INFO,
        "test_event",
        weird={1, 2, 3},
    )
    raw = captured_json._buf.getvalue().strip()  # type: ignore[attr-defined]
    data = json.loads(raw)
    # The fallback ``_bounded_json_default`` stringifies sets.
    assert "weird" in data
