"""Tests for ``ui.to_plain_text`` and ``middleware.rate_limiter.RateLimiter``.

These cover the two pieces of UI/middleware hardening from Phase 0:

* ``to_plain_text`` is the final fallback when HTML rendering fails.
* ``RateLimiter.cleanup`` bounds memory growth by dropping users that
  have been idle for at least one full window.
"""

import importlib.util
import os
import time

import pytest

# ``middleware/__init__.py`` does
#     from middleware.rate_limiter import RateLimiter, rate_limiter
# which causes the *attribute* ``middleware.rate_limiter`` to be the
# class, not the submodule — so a normal ``import middleware.rate_limiter``
# ends up rebinding the name to the class, never importing the module
# file. To get a real reference to the module object (so we can
# monkeypatch ``time.time`` on the same instance the production code
# reads from) we load the file directly via ``importlib``.
_RL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "middleware",
    "rate_limiter.py",
)
_spec = importlib.util.spec_from_file_location("_rl_module_under_test", _RL_FILE)
rl_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rl_module)

RateLimiter = rl_module.RateLimiter

from ui import to_plain_text


# ─── to_plain_text ───────────────────────────────────────────────────────────


def test_to_plain_text_removes_html_tags():
    """Every tag (open, close, self-closing) is stripped, leaving only text."""
    assert to_plain_text("<b>bold</b> and <i>italic</i>") == "bold and italic"
    assert to_plain_text("plain <span class='x'>inline</span> text") == "plain inline text"
    # Self-closing / void tags like <br>, <img> leave no text residue.
    assert to_plain_text("a<br>b<img src=x>c") == "abc"


def test_to_plain_text_unescapes_entities_safely():
    """Named/numeric entities must be decoded so the user sees real chars."""
    assert to_plain_text("&amp;") == "&"
    assert to_plain_text("&lt;tag&gt;") == "<tag>"
    assert to_plain_text("a &amp; b &lt; c") == "a & b < c"
    # Numeric entities are also supported by html.unescape.
    assert to_plain_text("&#65;&#66;") == "AB"


def test_to_plain_text_handles_none_and_empty():
    """Defensive: a None-ish input must not crash the renderer."""
    assert to_plain_text("") == ""
    assert to_plain_text(None) == ""  # type: ignore[arg-type]


# ─── RateLimiter.cleanup ─────────────────────────────────────────────────────


def test_cleanup_removes_users_whose_timestamps_are_all_stale(monkeypatch):
    """A user whose latest request is older than the window must be purged.

    We freeze the clock via monkeypatch so synthetic timestamps behave
    predictably regardless of wall-clock time.
    """
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    fake_now = [1_000_000.0]
    monkeypatch.setattr(rl_module.time, "time", lambda: fake_now[0])

    # Stale: newest timestamp is 90s old, well past the 60s window.
    limiter._requests[1001] = [fake_now[0] - 120.0, fake_now[0] - 90.0]
    # Still fresh: newest timestamp is 10s old.
    limiter._requests[1002] = [fake_now[0] - 30.0, fake_now[0] - 10.0]
    # Empty list — should also be reaped (can never affect a future decision).
    limiter._requests[1003] = []

    limiter.cleanup()

    assert 1001 not in limiter._requests  # fully stale
    assert 1002 in limiter._requests      # still active
    assert 1003 not in limiter._requests  # empty → reaped


def test_cleanup_keeps_user_with_one_recent_and_one_old_timestamp(monkeypatch):
    """Boundary: the user is alive as long as the *newest* timestamp is fresh."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    fake_now = [1_000_000.0]
    monkeypatch.setattr(rl_module.time, "time", lambda: fake_now[0])
    limiter._requests[2001] = [fake_now[0] - 120.0, fake_now[0] - 5.0]  # most recent wins

    limiter.cleanup()

    assert 2001 in limiter._requests
    # The stale entry can still be inside; the next is_allowed() call will
    # trim it. cleanup() only drops the key entirely, not the timestamps.
    assert limiter._requests[2001] == [fake_now[0] - 120.0, fake_now[0] - 5.0]


def test_cleanup_is_safe_on_empty_dict():
    """Calling cleanup on a fresh limiter must not raise."""
    RateLimiter(max_requests=5, window_seconds=60).cleanup()


# ─── RateLimiter.is_allowed (regression & new behavior) ──────────────────────


def test_is_allowed_still_blocks_too_many_requests():
    """The existing block-when-over-limit behavior is preserved."""
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    assert limiter.is_allowed(3001) is True
    assert limiter.is_allowed(3001) is True
    assert limiter.is_allowed(3001) is True
    # 4th request inside the window must be rejected.
    assert limiter.is_allowed(3001) is False


def test_is_allowed_admits_requests_after_window_passes(monkeypatch):
    """After ``window_seconds`` elapses, old timestamps slide out and the
    next request is allowed again — verified by monkeypatching ``time.time``.
    """
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    fake_now = [1_000_000.0]
    monkeypatch.setattr(rl_module.time, "time", lambda: fake_now[0])

    assert limiter.is_allowed(4001) is True
    assert limiter.is_allowed(4001) is True
    # At t=0+epsilon, the window hasn't slid yet → blocked.
    assert limiter.is_allowed(4001) is False

    # Jump 61s forward — both old timestamps are now older than 60s, so
    # they slide out and the new request is admitted.
    fake_now[0] += 61
    assert limiter.is_allowed(4001) is True
    # 2nd request inside the *new* window → still allowed (limit is 2).
    assert limiter.is_allowed(4001) is True
    # 3rd request inside the new window → rejected again, exactly like
    # the original "limit reached" behavior.
    assert limiter.is_allowed(4001) is False
    # Both fresh timestamps are inside the new window.
    assert len(limiter._requests[4001]) == 2


def test_is_allowed_is_per_user():
    """Hitting the limit for one user must not affect another."""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    assert limiter.is_allowed(5001) is True
    assert limiter.is_allowed(5001) is False
    # A different user still has full budget.
    assert limiter.is_allowed(5002) is True

