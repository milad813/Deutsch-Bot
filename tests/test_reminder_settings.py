"""Tests for the daily-reminder opt-in (Phase 0 hardening).

Reminders must be strictly opt-in. These tests guard the four repository
methods that back the toggle, plus the schema columns that hold the flag.
They run against the throwaway test database (see ``conftest.py``) so we
exercise the real SQL path including the upsert / join.
"""

import pytest

from services import db, run_db


# Use a high, unique UID range so the tests never collide with rows from
# other suites in the shared temp DB.
UID_ENABLED = 920_001
UID_DISABLED = 920_002
UID_INACTIVE = 920_003
UID_NO_SETTINGS = 920_004


async def _register_user(uid: int, username: str) -> None:
    """Insert a user row, mirroring what `register_user` does at runtime."""
    await run_db(
        db.users.register_user,
        user_id=uid,
        username=username,
        first_name="Rem",
        last_name="Test",
    )


async def _set_last_active(uid: int, days_ago: int) -> None:
    """Override ``last_active_at`` to ``N`` days ago for inactivity tests."""
    db.users.execute(
        "UPDATE users SET last_active_at = datetime('now', ?) WHERE user_id = ?",
        (f"-{days_ago} days", uid),
        commit=True,
    )


@pytest.fixture(autouse=True)
async def _seed():
    """Seed the four canonical user rows before every test.

    Cleanup is best-effort: we delete the rows we created so re-runs of
    the suite (which share the temp DB) start from a known state.
    """
    for uid in (UID_ENABLED, UID_DISABLED, UID_INACTIVE, UID_NO_SETTINGS):
        db.users.execute(
            "DELETE FROM user_settings WHERE user_id = ?", (uid,), commit=True
        )
        db.users.execute("DELETE FROM users WHERE user_id = ?", (uid,), commit=True)

    await _register_user(UID_ENABLED, "rem_enabled")
    await _register_user(UID_DISABLED, "rem_disabled")
    await _register_user(UID_INACTIVE, "rem_inactive")
    # UID_NO_SETTINGS: stays in ``users`` only, with no settings row.

    # Defaults: opt-in user, opted-out user, opted-in but stale user.
    await run_db(db.users.set_reminders_enabled, UID_ENABLED, True)
    await run_db(db.users.set_reminders_enabled, UID_DISABLED, False)
    await run_db(db.users.set_reminders_enabled, UID_INACTIVE, True)
    # Backdate the inactive user well past the 30-day window.
    await _set_last_active(UID_INACTIVE, 45)

    yield

    for uid in (UID_ENABLED, UID_DISABLED, UID_INACTIVE, UID_NO_SETTINGS):
        db.users.execute(
            "DELETE FROM user_settings WHERE user_id = ?", (uid,), commit=True
        )
        db.users.execute("DELETE FROM users WHERE user_id = ?", (uid,), commit=True)

# ─── default behavior ────────────────────────────────────────────────────────


async def test_default_reminders_enabled_is_false():
    """A user with no settings row is treated as opted-OUT."""
    assert await run_db(db.users.get_reminders_enabled, UID_NO_SETTINGS) is False


async def test_get_settings_returns_reminder_defaults_when_no_row():
    """``get_settings`` must still work (and report defaults) for new users."""
    settings = await run_db(db.users.get_settings, UID_NO_SETTINGS)
    assert settings == {}  # no row -> empty dict, as the existing API promises


# ─── set / toggle ────────────────────────────────────────────────────────────


async def test_set_reminders_enabled_upserts_and_persists():
    """``set_reminders_enabled(True)`` flips the flag and survives re-reads."""
    await run_db(db.users.set_reminders_enabled, UID_DISABLED, True)
    assert await run_db(db.users.get_reminders_enabled, UID_DISABLED) is True

    # And we can flip it back off.
    await run_db(db.users.set_reminders_enabled, UID_DISABLED, False)
    assert await run_db(db.users.get_reminders_enabled, UID_DISABLED) is False


async def test_set_reminders_enabled_creates_row_for_new_user():
    """Calling set on a user with no row yet must not crash on NOT NULL.

    The bootstrap insert uses the schema's documented defaults for the
    other columns.
    """
    assert await run_db(db.users.get_reminders_enabled, UID_NO_SETTINGS) is False

    await run_db(db.users.set_reminders_enabled, UID_NO_SETTINGS, True)
    assert await run_db(db.users.get_reminders_enabled, UID_NO_SETTINGS) is True

    # The other columns keep their schema defaults.
    settings = await run_db(db.users.get_settings, UID_NO_SETTINGS)
    assert settings["preferred_level"] == "A1"
    assert settings["daily_goal"] == 10
    assert settings["reminders_enabled"] is True
    assert settings["timezone_offset_minutes"] == 210


async def test_toggle_reminders_flips_value():
    """Two consecutive toggles must round-trip back to the original value."""
    # Start: opted in (per the fixture).
    assert await run_db(db.users.get_reminders_enabled, UID_ENABLED) is True

    new_after_first = await run_db(db.users.toggle_reminders, UID_ENABLED)
    assert new_after_first is False
    assert await run_db(db.users.get_reminders_enabled, UID_ENABLED) is False

    new_after_second = await run_db(db.users.toggle_reminders, UID_ENABLED)
    assert new_after_second is True
    assert await run_db(db.users.get_reminders_enabled, UID_ENABLED) is True


async def test_toggle_reminders_from_default_state():
    """First toggle on a brand-new user must enable the flag (not crash)."""
    assert await run_db(db.users.get_reminders_enabled, UID_NO_SETTINGS) is False
    new_value = await run_db(db.users.toggle_reminders, UID_NO_SETTINGS)
    assert new_value is True
    assert await run_db(db.users.get_reminders_enabled, UID_NO_SETTINGS) is True


# ─── get_reminder_user_ids (the join used by the daily_reminder job) ────────


async def test_get_reminder_user_ids_returns_only_opted_in_active_users():
    """The reminder list contains ONLY opted-in + active users.

    Fixture:
    - UID_ENABLED: opted in, just active  -> included
    - UID_DISABLED: opted out              -> excluded
    - UID_INACTIVE: opted in, >30d inactive -> excluded
    - UID_NO_SETTINGS: no row at all        -> excluded
    """
    recipients = await run_db(db.users.get_reminder_user_ids)
    assert recipients == [UID_ENABLED], recipients


async def test_get_reminder_user_ids_empty_when_nobody_opted_in():
    """If every user is opted out, the job must send zero reminders."""
    await run_db(db.users.set_reminders_enabled, UID_ENABLED, False)
    assert await run_db(db.users.get_reminder_user_ids) == []


async def test_get_reminder_user_ids_handles_no_settings_rows():
    """Users with no settings row at all must be skipped (not crash the join)."""
    # Wipe UID_ENABLED's settings row but keep the user; the join must
    # silently drop it because there's nothing to opt into.
    db.users.execute(
        "DELETE FROM user_settings WHERE user_id = ?", (UID_ENABLED,), commit=True
    )
    assert await run_db(db.users.get_reminder_user_ids) == []


async def test_get_reminder_user_ids_excludes_users_with_null_last_active():
    """A user with last_active_at = NULL must never be pinged.

    A null timestamp means "we have no idea when they were last around"
    — better to skip them than to risk a stale notification.
    """
    db.users.execute(
        "UPDATE users SET last_active_at = NULL WHERE user_id = ?",
        (UID_ENABLED,),
        commit=True,
    )
    assert await run_db(db.users.get_reminder_user_ids) == []


# ─── settings dict surface ───────────────────────────────────────────────────


async def test_get_settings_dict_includes_new_keys():
    """The settings dict must expose reminders_enabled and timezone."""
    settings = await run_db(db.users.get_settings, UID_ENABLED)
    assert "reminders_enabled" in settings
    assert "timezone_offset_minutes" in settings
    assert settings["reminders_enabled"] is True
    assert settings["timezone_offset_minutes"] == 210

