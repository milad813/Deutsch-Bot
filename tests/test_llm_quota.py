"""Tests for the daily LLM-quota system.

Covers the new ``LearningRepository`` methods that back the per-user
quota enforcement in ``handlers/story/core.py``,
``handlers/learning/flashcard_session.py`` and
``handlers/quiz_handlers.py``:

* ``is_llm_action_allowed`` — feature-aware allow/deny
* ``increment_llm_usage`` — atomic UPSERT that bumps the right counter
* ``get_llm_usage`` — date-partitioned read
* ``_today_local_str`` — local-timezone date key (covered indirectly via
  the public methods)

All tests run against the throwaway SQLite database configured in
``conftest.py`` so we exercise the real SQL path (UPSERT, date
partitioning, etc.) end-to-end. The configured ``LLM_DAILY_*_LIMIT``
values are temporarily lowered to a tiny budget so the tests don't have
to bump the counter 20 or 200 times just to prove the limit triggers.
"""

import importlib

import pytest

import config
from services import db, run_db


# Unique per-suite UID range so this file can share the temp DB with
# other suites without colliding on (user_id, usage_date) primary keys.
UID_BELOW = 950_001
UID_STORY_LIMIT = 950_002
UID_EXAMPLE_LIMIT = 950_003
UID_DAILY_OTHER = 950_004
UID_FRESH = 950_005

_DATE_A = "2024-01-15"
_DATE_B = "2024-01-16"


# ─── helpers ───────────────────────────────────────────────────────────────


def _wipe_llm_usage() -> None:
    """Remove every row this suite may have created.

    The temp DB persists across test invocations, so we clean up after
    ourselves rather than relying on tests running in a fixed order.
    """
    db.learning.execute(
        "DELETE FROM user_llm_usage WHERE user_id BETWEEN ? AND ?",
        (950_000, 950_999),
        commit=True,
    )


_SAVED_STORY_LIMIT = config.LLM_DAILY_STORY_LIMIT
_SAVED_EXAMPLE_LIMIT = config.LLM_DAILY_EXAMPLE_LIMIT


def _restore_limits() -> None:
    """Restore the real config limits (saved at import time)."""
    config.LLM_DAILY_STORY_LIMIT = _SAVED_STORY_LIMIT
    config.LLM_DAILY_EXAMPLE_LIMIT = _SAVED_EXAMPLE_LIMIT


@pytest.fixture(autouse=True)
async def _clean_and_reload():
    """Wipe the table before each test and re-bind the real limits.

    We also reload ``config`` so any side-effect from another test that
    monkey-patched module-level constants can't leak into this suite.
    """
    _wipe_llm_usage()
    importlib.reload(config)
    _restore_limits()
    yield
    _wipe_llm_usage()
    _restore_limits()


# ─── is_llm_action_allowed ────────────────────────────────────────────────


async def test_is_llm_action_allowed_true_when_below_limit():
    """A fresh user with zero usage must be allowed for both features."""
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_BELOW, "story"
    ) is True
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_BELOW, "example"
    ) is True


async def test_is_llm_action_allowed_false_when_story_limit_reached():
    """Once story_count == story_limit, the next request must be denied.

    We lower the configured limit to 2 so the test stays tiny while still
    proving the boundary behaviour (one call under the limit, one at the
    limit, the next one denied).
    """
    config.LLM_DAILY_STORY_LIMIT = 2

    # First call: still allowed.
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_STORY_LIMIT, "story"
    ) is True
    await run_db(db.learning.increment_llm_usage, UID_STORY_LIMIT, "story")

    # Second call: count is now 1, still under limit of 2.
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_STORY_LIMIT, "story"
    ) is True
    await run_db(db.learning.increment_llm_usage, UID_STORY_LIMIT, "story")

    # Third check: count is 2, equal to limit -> not allowed.
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_STORY_LIMIT, "story"
    ) is False


async def test_is_llm_action_allowed_false_when_example_limit_reached():
    """Same boundary check, but for the example quota."""
    config.LLM_DAILY_EXAMPLE_LIMIT = 3

    for _ in range(3):
        assert await run_db(
            db.learning.is_llm_action_allowed, UID_EXAMPLE_LIMIT, "example"
        ) is True
        await run_db(
            db.learning.increment_llm_usage, UID_EXAMPLE_LIMIT, "example"
        )

    # 4th request hits the cap -> denied.
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_EXAMPLE_LIMIT, "example"
    ) is False


async def test_is_llm_action_allowed_uses_strict_less_than():
    """Boundary: exactly ``limit`` consumed is still allowed on the way up,
    and only the *next* call is rejected.

    With a limit of 1, a brand-new user can perform exactly one call.
    """
    config.LLM_DAILY_STORY_LIMIT = 1

    # Brand-new user: 0 < 1 -> allowed.
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_FRESH, "story"
    ) is True
    # Consume the single allowed call.
    await run_db(db.learning.increment_llm_usage, UID_FRESH, "story")
    # Now 1 is NOT < 1 -> denied.
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_FRESH, "story"
    ) is False


async def test_is_llm_action_allowed_unknown_feature_is_denied():
    """Defensive: an unknown feature name must not silently grant access.

    Otherwise a typo like ``"stroy"`` would let every request through
    because the method would just return ``True`` for the no-row case.
    """
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_BELOW, "stroy"
    ) is False
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_BELOW, ""
    ) is False


async def test_is_llm_action_allowed_independent_per_feature():
    """Saturating one feature must not block the other."""
    config.LLM_DAILY_STORY_LIMIT = 1
    config.LLM_DAILY_EXAMPLE_LIMIT = 1

    # Use up the example quota; story quota should still be open.
    await run_db(db.learning.increment_llm_usage, UID_DAILY_OTHER, "example")
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_DAILY_OTHER, "example"
    ) is False
    assert await run_db(
        db.learning.is_llm_action_allowed, UID_DAILY_OTHER, "story"
    ) is True


# ─── increment_llm_usage ──────────────────────────────────────────────────


async def test_increment_llm_usage_story_count_increases():
    """Each call must add exactly 1 to story_count on the current day."""
    usage_before = await run_db(db.learning.get_llm_usage, UID_BELOW)
    assert usage_before == {"story": 0, "example": 0}

    await run_db(db.learning.increment_llm_usage, UID_BELOW, "story")
    await run_db(db.learning.increment_llm_usage, UID_BELOW, "story")
    await run_db(db.learning.increment_llm_usage, UID_BELOW, "story")

    usage_after = await run_db(db.learning.get_llm_usage, UID_BELOW)
    assert usage_after["story"] == 3
    assert usage_after["example"] == 0  # other counter untouched


async def test_increment_llm_usage_example_count_increases():
    """Each call must add exactly 1 to example_count on the current day."""
    await run_db(db.learning.increment_llm_usage, UID_BELOW, "example")
    await run_db(db.learning.increment_llm_usage, UID_BELOW, "example")

    usage = await run_db(db.learning.get_llm_usage, UID_BELOW)
    assert usage["example"] == 2
    assert usage["story"] == 0  # other counter untouched


async def test_increment_llm_usage_unknown_feature_is_noop():
    """An unknown feature name must be a silent no-op (no row created,
    no exception). This matches the spec: ``feature`` can only be
    ``"story"`` or ``"example"``."""
    await run_db(db.learning.increment_llm_usage, UID_FRESH, "bogus")

    usage = await run_db(db.learning.get_llm_usage, UID_FRESH)
    assert usage == {"story": 0, "example": 0}


async def test_increment_llm_usage_updates_last_updated():
    """Every UPSERT must touch the ``last_updated`` timestamp so audits
    can tell which day a consumption was recorded on."""
    await run_db(db.learning.increment_llm_usage, UID_BELOW, "story")

    row = db.learning.fetch_one(
        "SELECT last_updated FROM user_llm_usage WHERE user_id = ?",
        (UID_BELOW,),
    )
    assert row is not None
    # The exact format is opaque to the spec, but the column must be
    # non-empty after a write.
    assert row[0] is not None and str(row[0]).strip() != ""


# ─── usage is separated by date ──────────────────────────────────────────


async def test_usage_is_separated_by_date():
    """Quota rows are partitioned by ``usage_date``; bumping the counter
    on day A must not affect day B.

    We pin both dates explicitly via the optional ``usage_date`` kwarg
    so the test is independent of the actual wall-clock day.
    """
    # Day A: two stories consumed.
    await run_db(
        db.learning.increment_llm_usage, UID_DAILY_OTHER, "story", _DATE_A
    )
    await run_db(
        db.learning.increment_llm_usage, UID_DAILY_OTHER, "story", _DATE_A
    )

    # Day B: nothing consumed yet.
    day_b_usage = await run_db(
        db.learning.get_llm_usage, UID_DAILY_OTHER, _DATE_B
    )
    assert day_b_usage == {"story": 0, "example": 0}

    # Adding 1 on day B must not change day A.
    await run_db(
        db.learning.increment_llm_usage, UID_DAILY_OTHER, "example", _DATE_B
    )

    day_a_after = await run_db(
        db.learning.get_llm_usage, UID_DAILY_OTHER, _DATE_A
    )
    day_b_after = await run_db(
        db.learning.get_llm_usage, UID_DAILY_OTHER, _DATE_B
    )

    assert day_a_after == {"story": 2, "example": 0}
    assert day_b_after == {"story": 0, "example": 1}

    # And the same user has two distinct rows in the table.
    rows = db.learning.fetch_all(
        "SELECT usage_date, story_count, example_count "
        "FROM user_llm_usage WHERE user_id = ? "
        "ORDER BY usage_date",
        (UID_DAILY_OTHER,),
    )
    assert rows == [(_DATE_A, 2, 0), (_DATE_B, 0, 1)]


async def test_today_local_str_is_a_yyyy_mm_dd_string():
    """The partition key must always be a 10-char ``YYYY-MM-DD`` string
    so it sorts and compares correctly as TEXT in SQLite.
    """
    today = db.learning._today_local_str()
    assert isinstance(today, str)
    assert len(today) == 10
    # Cheap structural check; avoids importing datetime just to parse.
    year, sep1, rest = today.partition("-")
    month, sep2, day = rest.partition("-")
    assert sep1 == "-" and sep2 == "-"
    assert len(year) == 4 and year.isdigit()
    assert len(month) == 2 and month.isdigit()
    assert len(day) == 2 and day.isdigit()
