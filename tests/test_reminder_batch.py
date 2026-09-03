"""Tests for the batched daily-reminder pipeline (Phase 1, item 5).

The Phase 0 reminder job had three production hazards:

* it ran FOUR queries per recipient (due / hard / goal / today-new);
* it sent a chat message to every opted-in user, even users with
  nothing to review;
* it had no per-batch pause and no ``RetryAfter`` handling, so a
  flood-hit would either crash the job or hammer Telegram.

The Phase 1 rewrite addresses all three with four new
``UserRepository`` batch methods + a reworked ``daily_reminder`` job.
These tests guard both layers:

1. The repository methods return the right ``{user_id: count}`` maps,
   short-circuit on an empty input, and never include rows for users
   that were not in the input list.
2. The default daily goal for a user with no ``user_settings`` row
   stays at 10 (the same value the single-user ``get_daily_goal``
   has always returned).
3. The ``daily_reminder`` job never sends a message to a user that
   ``get_reminder_user_ids`` excluded (i.e. opted-out / inactive),
   and never sends a message to a user that has nothing to review
   (due_count == 0 AND hard_count == 0).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from bot import daily_reminder
from services import config, db

# ─── fixtures ───────────────────────────────────────────────────────────

UID_INCLUDED = 950_001
UID_OTHER = 950_002
UID_NO_DATA = 950_003
UID_OPTED_OUT = 950_004
UID_INACTIVE = 950_005


def _register_sync(user_id: int, username: str = "u") -> None:
    """Insert a user row synchronously (no ``await``)."""
    db.users.register_user(
        user_id=user_id,
        username=username,
        first_name="Rem",
        last_name="Batch",
    )


def _set_last_active_sync(user_id: int, days_ago: int) -> None:
    """Backdate ``last_active_at`` for inactivity tests."""
    db.users.execute(
        "UPDATE users SET last_active_at = datetime('now', ?) WHERE user_id = ?",
        (f"-{days_ago} days", user_id),
        commit=True,
    )


def _delete_for(uid: int) -> None:
    """Wipe every row this test created for a user (cleanup helper)."""
    db.users.execute(
        "DELETE FROM word_stats WHERE user_id = ?", (uid,), commit=True
    )
    db.users.execute(
        "DELETE FROM words WHERE user_id = ?", (uid,), commit=True
    )
    db.users.execute(
        "DELETE FROM user_settings WHERE user_id = ?", (uid,), commit=True
    )
    db.users.execute("DELETE FROM users WHERE user_id = ?", (uid,), commit=True)


def _seed_word_stats_sync(
    user_id: int,
    *,
    due: int = 0,
    hard: int = 0,
    new_today: int = 0,
) -> None:
    """Insert ``word_stats`` rows that drive the batch aggregations.

    * ``due`` rows with ``next_review`` <= now and phase='review' --
      counted by the *due* map only.
    * ``hard`` rows with ``phase='learning'`` and ``next_review`` <= now
      -- counted by BOTH the due and hard maps.
    * ``new_today`` rows with ``last_reviewed`` set to "right now" --
      counted by the today-new map only.

    ``word_stats`` has a UNIQUE constraint on ``(user_id, word_id)``,
    so we need a fresh parent ``words`` row per stat row.
    """
    _delete_words_for(user_id)
    db.users.execute(
        "DELETE FROM word_stats WHERE user_id = ?", (user_id,), commit=True
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    overdue = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    total = due + hard + new_today
    # Insert one parent word per stat row so the UNIQUE(user_id,
    # word_id) constraint on word_stats is satisfied.
    word_ids: List[int] = []
    for i in range(total):
        with db.users.cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO words (german, persian) VALUES (?, ?)",
                (f"wort_{user_id}_{i}", f"کلمه_{user_id}_{i}"),
            )
            word_ids.append(cur.lastrowid)

    rows: List[tuple] = []
    idx = 0
    for _ in range(due):
        rows.append(
            (user_id, word_ids[idx], 0, 0, 2.5, 1.0, 0, now, overdue, "review")
        )
        idx += 1
    for _ in range(hard):
        rows.append(
            (user_id, word_ids[idx], 0, 0, 2.5, 1.0, 0, now, overdue, "learning")
        )
        idx += 1
    for _ in range(new_today):
        rows.append(
            (user_id, word_ids[idx], 0, 0, 2.5, 1.0, 0, now, None, "new")
        )
        idx += 1

    for r in rows:
        db.users.execute(
            """INSERT INTO word_stats (
                user_id, word_id, correct_count, wrong_count, ease_factor,
                interval_days, srs_level, last_reviewed, next_review, phase
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            r,
            commit=True,
        )


def _delete_words_for(user_id: int) -> None:
    """Wipe any parent words this test created for ``user_id``."""
    db.users.execute(
        "DELETE FROM words WHERE user_id = ?", (user_id,), commit=True
    )


@pytest.fixture(autouse=True)
def _seed():
    """Seed the four canonical users + cross-suite cleanup.

    ``autouse=True`` so the seeding runs even for the two tests that
    do not need ``_seed_word_stats_sync``.  Phase 0 schema is exercised
    implicitly: ``set_reminders_enabled`` upserts a row, so the test
    also confirms the migrations are in place.
    """
    for uid in (
        UID_INCLUDED,
        UID_OTHER,
        UID_NO_DATA,
        UID_OPTED_OUT,
        UID_INACTIVE,
    ):
        _delete_for(uid)

    for uid, name in (
        (UID_INCLUDED, "u_inc"),
        (UID_OTHER, "u_other"),
        (UID_NO_DATA, "u_nodata"),
        (UID_OPTED_OUT, "u_out"),
        (UID_INACTIVE, "u_inact"),
    ):
        _register_sync(uid, name)

    # Phase 0's ``get_reminder_user_ids`` requires a ``user_settings``
    # row with ``reminders_enabled = 1`` to even consider a user, so
    # every user we want on the recipient list needs the upsert
    # called on them.  The default value of the column is 0, so
    # calling ``set_reminders_enabled(uid, True)`` is the only way
    # to flip it for users that don't already have a settings row.
    db.users.set_reminders_enabled(UID_INCLUDED, True)
    db.users.set_reminders_enabled(UID_OTHER, True)
    db.users.set_reminders_enabled(UID_NO_DATA, True)
    db.users.set_reminders_enabled(UID_OPTED_OUT, False)
    db.users.set_reminders_enabled(UID_INACTIVE, True)
    _set_last_active_sync(UID_INACTIVE, 45)

    # Sanity: the Phase 0 recipient list must contain exactly the
    # three active opted-in users; the opted-out one AND the inactive
    # one must both be missing.
    recipients = db.users.get_reminder_user_ids()
    expected = {UID_INCLUDED, UID_OTHER, UID_NO_DATA}
    assert UID_OPTED_OUT not in recipients
    assert UID_INACTIVE not in recipients
    assert set(recipients) == expected, recipients

    yield

    for uid in (
        UID_INCLUDED,
        UID_OTHER,
        UID_NO_DATA,
        UID_OPTED_OUT,
        UID_INACTIVE,
    ):
        _delete_for(uid)


# ─── batch repository methods ──────────────────────────────────────────


def test_get_due_counts_for_users_only_returns_given_users():
    """``get_due_counts_for_users`` must:
    * return a count only for users that are in the input list;
    * omit users with no due words (the caller treats that as 0);
    * short-circuit on an empty input list (no SQL run).
    """
    # Two users with data, one with nothing.  We deliberately include
    # UID_OTHER in the input so we can confirm the count is right and
    # UID_OPTED_OUT so we can confirm it never appears in the output
    # (it has no word_stats rows anyway, but the contract is "only
    # the input list, nothing else").
    _seed_word_stats_sync(UID_INCLUDED, due=3, hard=0, new_today=0)
    _seed_word_stats_sync(UID_OTHER, due=1, hard=2, new_today=0)
    _seed_word_stats_sync(UID_NO_DATA, due=0, hard=0, new_today=0)

    # Empty input -> empty output, no SQL.
    assert db.users.get_due_counts_for_users([]) == {}

    # Real call: counts are (due + hard) for each user, since both
    # kinds of rows have ``next_review <= now``.  UID_NO_DATA has no
    # rows so it must NOT appear in the returned map.  UID_OPTED_OUT
    # is also excluded because the caller is responsible for the
    # opt-in filter.
    result = db.users.get_due_counts_for_users(
        [UID_INCLUDED, UID_OTHER, UID_NO_DATA, UID_OPTED_OUT]
    )
    assert result == {UID_INCLUDED: 3, UID_OTHER: 3}, result
    # Users with no rows must be OMITTED, not returned as 0.
    assert UID_NO_DATA not in result
    assert UID_OPTED_OUT not in result


def test_get_hard_due_counts_for_users_only_returns_given_users():
    """``get_hard_due_counts_for_users`` must filter on phase='learning'."""
    _seed_word_stats_sync(UID_INCLUDED, due=2, hard=5, new_today=0)
    _seed_word_stats_sync(UID_OTHER, due=10, hard=0, new_today=0)
    _seed_word_stats_sync(UID_NO_DATA, due=0, hard=0, new_today=0)

    assert db.users.get_hard_due_counts_for_users([]) == {}

    result = db.users.get_hard_due_counts_for_users(
        [UID_INCLUDED, UID_OTHER, UID_NO_DATA, UID_OPTED_OUT]
    )
    # Only the learning-phase rows count.
    assert result == {UID_INCLUDED: 5}, result
    # ``due`` rows alone (UID_OTHER) must NOT be counted as hard.
    assert UID_OTHER not in result
    assert UID_NO_DATA not in result
    assert UID_OPTED_OUT not in result


def test_get_daily_goals_for_users_defaults_to_10_when_missing():
    """The default for a user with no ``user_settings`` row is 10."""
    # UID_NO_DATA: present in ``users`` but with no settings row.
    # UID_INCLUDED: gets an explicit goal of 7.
    db.users.execute(
        "DELETE FROM user_settings WHERE user_id = ?",
        (UID_NO_DATA,),
        commit=True,
    )
    db.learning.set_daily_goal(UID_INCLUDED, 7)
    # UID_OTHER: stays with the schema default of 10 (no row was set
    # by this test, but the autouse fixture ran ``set_reminders_enabled``
    # which *does* create a row with goal=10).
    goal_other = db.learning.get_daily_goal(UID_OTHER)
    assert goal_other == 10

    # Empty input -> empty output.
    assert db.users.get_daily_goals_for_users([]) == {}

    result = db.users.get_daily_goals_for_users(
        [UID_INCLUDED, UID_OTHER, UID_NO_DATA, UID_OPTED_OUT]
    )
    # Explicit user: 7.  Users with a settings row but no custom goal
    # (UID_OTHER, UID_OPTED_OUT): 10.  User with no row (UID_NO_DATA):
    # also 10 -- the default.
    assert result == {
        UID_INCLUDED: 7,
        UID_OTHER: 10,
        UID_NO_DATA: 10,
        UID_OPTED_OUT: 10,
    }, result


def test_get_today_new_counts_for_users_zero_for_users_with_no_activity():
    """Users with no ``word_stats`` row today must be omitted (= 0)."""
    _seed_word_stats_sync(UID_INCLUDED, due=0, hard=0, new_today=4)
    _seed_word_stats_sync(UID_OTHER, due=0, hard=0, new_today=1)
    # UID_NO_DATA: no rows at all.
    # UID_OPTED_OUT / UID_INACTIVE: also no rows.

    assert db.users.get_today_new_counts_for_users([]) == {}

    result = db.users.get_today_new_counts_for_users(
        [UID_INCLUDED, UID_OTHER, UID_NO_DATA, UID_OPTED_OUT, UID_INACTIVE]
    )
    assert result == {UID_INCLUDED: 4, UID_OTHER: 1}, result
    # No-activity users must be omitted, not returned as 0.
    for uid in (UID_NO_DATA, UID_OPTED_OUT, UID_INACTIVE):
        assert uid not in result, (uid, result)


# ─── daily_reminder skips users with reminders disabled ────────────────


class _FakeBot:
    """Minimal stand-in for the ``telegram.Bot`` used in daily_reminder.

    ``daily_reminder`` only ever calls ``bot.send_message(chat_id=...)``.
    We record each call so the test can assert which user ids the job
    pinged.
    """

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    async def send_message(self, chat_id=None, text=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})


def _patch_job(monkeypatch, *, recipients, due_map, hard_map, goal_map, today_map):
    """Patch every external the job touches except the bot itself.

    Returns the ``_FakeBot`` instance the test should read from.
    """
    bot = _FakeBot()
    monkeypatch.setattr(db.users, "get_reminder_user_ids", lambda: recipients)
    monkeypatch.setattr(
        db.users, "get_due_counts_for_users", lambda ids: due_map
    )
    monkeypatch.setattr(
        db.users, "get_hard_due_counts_for_users", lambda ids: hard_map
    )
    monkeypatch.setattr(
        db.users, "get_daily_goals_for_users", lambda ids: goal_map
    )
    monkeypatch.setattr(
        db.users, "get_today_new_counts_for_users", lambda ids: today_map
    )
    # Allow every "user" through the auth check.
    monkeypatch.setattr(config, "is_authorized_user", lambda uid: True)
    # Pin a tiny batch size so the test exercises the batching path
    # even with a 4-recipient list (we want a 2-batch run).
    monkeypatch.setattr(config, "REMINDER_BATCH_SIZE", 2)
    # Keep the inter-batch sleep cheap so the test runs in ms, not s.
    monkeypatch.setattr(config, "REMINDER_SLEEP_SECONDS", 0.0)
    return bot


async def test_daily_reminder_skips_users_with_reminders_disabled(monkeypatch):
    """``daily_reminder`` must never send a message to a user that
    ``get_reminder_user_ids`` excluded — i.e. opted-out or inactive.

    The job's source-of-truth for "should this user get a reminder?"
    is the recipient list returned by ``get_reminder_user_ids``.  We
    stub that to return only ``UID_INCLUDED``; ``UID_OPTED_OUT`` and
    ``UID_INACTIVE`` must never be reached regardless of what the
    batch methods report.
    """
    bot = _patch_job(
        monkeypatch,
        recipients=[UID_INCLUDED],  # Phase 0 list (already filtered)
        due_map={UID_INCLUDED: 5, UID_OPTED_OUT: 5, UID_INACTIVE: 5},
        hard_map={},
        goal_map={UID_INCLUDED: 10},
        today_map={},
    )

    ctx = SimpleNamespace(bot=bot)
    await daily_reminder(ctx)

    # The only user that got a chat message is the one Phase 0
    # authorised.
    chat_ids = [m["chat_id"] for m in bot.sent]
    assert chat_ids == [UID_INCLUDED], chat_ids
    # And the message mentions the due count we put in the map.
    assert "5" in bot.sent[0]["text"]


async def test_daily_reminder_skips_users_with_nothing_to_review(monkeypatch):
    """``daily_reminder`` must NOT send a chat message to a user with
    ``due_count == 0 AND hard_count == 0``, even if the user is on
    the recipient list.  The user opted in to *reminders*, not to a
    daily "all good" notification.
    """
    bot = _patch_job(
        monkeypatch,
        recipients=[UID_INCLUDED, UID_OTHER, UID_NO_DATA],
        due_map={UID_INCLUDED: 3, UID_OTHER: 0, UID_NO_DATA: 0},
        hard_map={UID_INCLUDED: 0, UID_OTHER: 0, UID_NO_DATA: 0},
        goal_map={UID_INCLUDED: 10, UID_OTHER: 10, UID_NO_DATA: 10},
        today_map={UID_INCLUDED: 1, UID_OTHER: 0, UID_NO_DATA: 0},
    )

    ctx = SimpleNamespace(bot=bot)
    await daily_reminder(ctx)

    chat_ids = [m["chat_id"] for m in bot.sent]
    assert chat_ids == [UID_INCLUDED], chat_ids


async def test_daily_reminder_no_op_when_recipient_list_is_empty(monkeypatch):
    """If nobody opted in, the job must not touch the network.

    This is the "all opted out" / "no recipients" case.  We assert
    that no chat message was sent; the early return inside
    ``daily_reminder`` (``if not user_ids: return``) guarantees the
    batch methods are never called either.
    """
    bot = _patch_job(
        monkeypatch,
        recipients=[],
        due_map={},
        hard_map={},
        goal_map={},
        today_map={},
    )

    ctx = SimpleNamespace(bot=bot)
    await daily_reminder(ctx)

    assert bot.sent == []
