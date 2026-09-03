"""Structured logging helpers.

Operational events in the bot are emitted via :func:`log_event`
so that:

1. They have a stable, machine-friendly name (``event=...``) for
   dashboarding / alerting.
2. They carry structured context (user_id, lesson_id, retry_after,
   error type, ...) instead of being squeezed into a free-form
   message string.
3. They never leak secrets -- the redaction pass below scrubs
   common secret field names and full LLM prompts before either
   the JSON or the text formatter sees them.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

# Reserved ``LogRecord`` attributes (stdlib ``logging`` docs).
_RESERVED_LOG_ATTRS: frozenset = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)

# Subset of the above excluded from the JSON payload.
_INTERNAL_LOG_ATTRS: frozenset = frozenset(
    {
        "args",
        "msg",
        "levelno",
        "msecs",
        "relativeCreated",
        "taskName",
    }
)

# Field names that must never end up in a log line.
_SECRET_KEY_PATTERNS: frozenset = frozenset(
    {
        "telegram_bot_token",
        "bot_token",
        "token",
        "groq_api_key",
        "groq_api_keys",
        "api_key",
        "api_keys",
        "password",
        "passwd",
        "secret",
        "authorization",
        "auth",
        "bearer",
    }
)

# User-supplied content fields; the *value* is fully redacted.
_USER_CONTENT_KEY_PATTERNS: frozenset = frozenset(
    {
        "user_message",
        "message_text",
        "input_text",
        "callback_data",
    }
)

# LLM prompt fields; the *value* is truncated to a short shape.
_PROMPT_KEY_PATTERNS: frozenset = frozenset(
    {
        "prompt",
        "full_prompt",
        "messages",
        "system_prompt",
    }
)

_REDACTED = "***REDACTED***"
_PROMPT_HEAD = 80
_PROMPT_TAIL = 80
_PROMPT_MAX_TOTAL = _PROMPT_HEAD + len("\u2026") + _PROMPT_TAIL
# Hard cap on any *string* value in the JSON output.
_MAX_STRING_VALUE = 2048


def _normalise(key: Any) -> str:
    """Lower-case + snake-case the key for pattern matching."""
    s = str(key).strip().lower()
    for sep in ("-", " ", "/", "."):
        s = s.replace(sep, "_")
    return s


def _is_secret_key(key: Any) -> bool:
    n = _normalise(key)
    if n in _SECRET_KEY_PATTERNS:
        return True
    for pat in _SECRET_KEY_PATTERNS:
        if n.endswith("_" + pat) or n == pat:
            return True
    return False


def _is_user_content_key(key: Any) -> bool:
    return _normalise(key) in _USER_CONTENT_KEY_PATTERNS


def _is_prompt_key(key: Any) -> bool:
    return _normalise(key) in _PROMPT_KEY_PATTERNS


def _truncate_prompt(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= _PROMPT_MAX_TOTAL:
        return value
    return value[:_PROMPT_HEAD] + "\u2026" + value[-_PROMPT_TAIL:]


def _scrub_value(key: Any, value: Any) -> Any:
    """Return a redacted/truncated form of ``value`` for log output."""
    if _is_secret_key(key):
        return _REDACTED
    if _is_user_content_key(key):
        return _REDACTED
    if _is_prompt_key(key):
        return _truncate_prompt(value)
    return value


def _scrub(obj: Any) -> Any:
    """Recursively walk a log payload, scrubbing secret / user fields."""
    if isinstance(obj, Mapping):
        return {str(k): _scrub(_scrub_value(k, v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        cleaned = [_scrub(v) for v in obj]
        return type(obj)(cleaned) if isinstance(obj, tuple) else cleaned
    return obj


def _scrub_fields(fields: Mapping[str, Any]) -> Dict[str, Any]:
    """Scrub a flat dict of ``**fields`` for ``log_event``."""
    out: Dict[str, Any] = {}
    for k, v in fields.items():
        key = str(k)
        scrubbed = _scrub(_scrub_value(key, v))
        out[key] = scrubbed
    return out


def _format_kv(fields: Mapping[str, Any]) -> str:
    """Render a flat ``**fields`` dict as a ``k=v k=v`` suffix."""

    def _render(v: Any) -> str:
        if isinstance(v, str):
            if len(v) > 120:
                return repr(v[:117] + "\u2026")
            return v
        if isinstance(v, (int, float, bool)) or v is None:
            return repr(v)
        r = repr(v)
        if len(r) > 160:
            return r[:157] + "\u2026"
        return r

    parts = []
    for k, v in fields.items():
        parts.append(f"{k}={_render(v)}")
    return " ".join(parts)


def _bounded_json_default(o: Any) -> Any:
    """``json.dumps`` default that never explodes on weird types."""
    try:
        return str(o)
    except Exception:
        return f"<unserializable:{type(o).__name__}>"


def _stringify_strings(obj: Any) -> Any:
    """Bound every string in the JSON payload to ``_MAX_STRING_VALUE``."""
    if isinstance(obj, Mapping):
        return {k: _stringify_strings(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        cleaned = [_stringify_strings(v) for v in obj]
        return type(obj)(cleaned) if isinstance(obj, tuple) else cleaned
    if isinstance(obj, str) and len(obj) > _MAX_STRING_VALUE:
        return obj[: _MAX_STRING_VALUE - 1] + "\u2026"
    return obj


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON.

    The JSON object always contains at least:

    * ``timestamp`` -- ISO 8601 UTC with a trailing ``Z``.
    * ``level`` -- uppercase level name (``INFO`` / ``WARNING`` ...).
    * ``logger`` -- the logger name.
    * ``message`` -- the formatted log message.

    Any field passed via ``extra=`` to ``logger.log(...)`` or
    :func:`log_event` is included as a top-level key, with secret
    fields redacted and prompt-shaped strings truncated.
    """

    def format(self, record: logging.LogRecord) -> str:
        extras: Dict[str, Any] = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RESERVED_LOG_ATTRS and k not in _INTERNAL_LOG_ATTRS
        }

        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(extras)

        # Scrub, then bound string sizes.
        payload = _stringify_strings(_scrub(payload))

        if record.exc_info:
            try:
                payload["exception"] = self.formatException(record.exc_info)
            except Exception:
                payload["exception"] = "<failed to render exception>"
        if record.stack_info:
            try:
                payload["stack"] = self.formatStack(record.stack_info)
            except Exception:
                payload["stack"] = "<failed to render stack>"

        try:
            return json.dumps(
                payload, default=_bounded_json_default, ensure_ascii=False
            )
        except (TypeError, ValueError) as exc:
            fallback = {
                "timestamp": payload.get("timestamp"),
                "level": "ERROR",
                "logger": record.name,
                "message": f"<log formatter failed: {exc}>",
            }
            return json.dumps(fallback, ensure_ascii=False)


class TextWithExtrasFormatter(logging.Formatter):
    """Default-style text formatter that also surfaces ``extra`` fields.

    The standard format string is::

        %(asctime)s - %(name)s - %(levelname)s - %(message)s [key=value ...]

    If a record was emitted with ``extra={"event": "..."}`` the
    ``event`` value is appended first, then any other extras are
    appended as ``key=value`` pairs.  If there are no extras the
    suffix is omitted so existing log lines stay byte-identical.
    """

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt=None,
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras: Dict[str, Any] = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RESERVED_LOG_ATTRS and k not in _INTERNAL_LOG_ATTRS
        }
        if not extras:
            return base
        extras = _stringify_strings(_scrub(extras))
        return base + " " + _format_kv(extras)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *fields: Any,
    **kw_fields: Any,
) -> None:
    """Emit a structured operational event.

    Parameters
    ----------
    logger:
        The logger to use (e.g. ``logging.getLogger(__name__)``).
    level:
        A ``logging`` level constant (``logging.INFO`` ...).
    event:
        Stable, machine-friendly event name.  Convention: lower
        snake-case (``story_generation_failed``,
        ``reminder_batch_started`` ...).  Do *not* include user
        data in the event name; that belongs in ``**fields``.
    *fields:
        Optional positional values that will be merged into the
        field dict as ``"arg_0"``, ``"arg_1"``, ...  Most callers
        should use keyword arguments instead.
    **kw_fields:
        Structured context.  Reserved / secret-looking keys are
        scrubbed automatically; see the module docstring.

    The event name appears in:

    * The text message body as ``event=<name>`` followed by the
      ``k=v`` suffix, so ``grep event=story_generation_failed``
      works on plain text logs.
    * The JSON payload as a top-level ``"event"`` key, so
      log-aggregator queries can filter directly.

    Examples
    --------
    >>> log_event(
    ...     logger, logging.INFO,
    ...     "story_generation_failed",
    ...     user_id=1, lesson_id=2, error="boom",
    ... )
    """
    if not event or not isinstance(event, str):
        raise ValueError("event must be a non-empty string")

    merged: Dict[str, Any] = {}
    for i, v in enumerate(fields):
        merged[f"arg_{i}"] = v
    merged.update(kw_fields)

    scrubbed = _scrub_fields(merged)
    rendered_kv = _format_kv(scrubbed)
    message = f"event={event} {rendered_kv}".rstrip()

    extra: Dict[str, Any] = {"event": event}
    extra.update(scrubbed)

    logger.log(level, message, extra=extra)


__all__ = [
    "JsonFormatter",
    "TextWithExtrasFormatter",
    "log_event",
]
