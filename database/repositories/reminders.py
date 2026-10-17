"""Reminder preferences and batch statistics."""

from typing import Dict, List
from database.repositories.base import BaseRepository


class ReminderRepository(BaseRepository):
    def get_reminders_enabled(self, user_id: int) -> bool:
        """Read the reminder opt-in flag; default = False (opt-out)."""
        row = self.fetch_one(
            "SELECT reminders_enabled FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        if not row or row[0] is None:
            return False
        return bool(row[0])

    def set_reminders_enabled(self, user_id: int, enabled: bool) -> None:
        """Upsert the reminder flag; bootstrap defaults for other columns.

        If no ``user_settings`` row exists yet, insert one with the same
        defaults the schema uses (``preferred_level='A1'``,
        ``daily_goal=10``) so we never trip a NOT NULL constraint.
        """
        self.execute(
            """
            INSERT INTO user_settings
                (user_id, preferred_level, daily_goal, reminders_enabled,
                 timezone_offset_minutes)
            VALUES (?, 'A1', 10, ?, 210)
            ON CONFLICT(user_id) DO UPDATE SET
                reminders_enabled = excluded.reminders_enabled
            """,
            (user_id, 1 if enabled else 0),
            commit=True,
        )

    def toggle_reminders(self, user_id: int) -> bool:
        """Flip the reminder flag and return the new value."""
        with self._conn.transaction():
            new_value = not self.get_reminders_enabled(user_id)
            self.set_reminders_enabled(user_id, new_value)
            return new_value

    def get_reminder_user_ids(self) -> List[int]:
        """Return ids of users who opted in AND were active in the last 30 days.

        Inactive users are filtered out so we never ping someone who has
        effectively stopped using the bot.
        """
        rows = self.fetch_all(
            """
            SELECT u.user_id
            FROM users u
            JOIN user_settings s ON s.user_id = u.user_id
            WHERE s.reminders_enabled = 1
              AND u.last_active_at IS NOT NULL
              AND u.last_active_at >= datetime('now', '-30 days')
            """
        )
        return [r[0] for r in rows]

    def _check_int_user_ids(self, user_ids: List[int]) -> None:
        """Validate ``user_ids`` for the batch helpers.

        A bad list (None, wrong type, mixed types) is a programmer
        error and must surface loudly. We explicitly reject ``bool``
        even though ``bool`` is a subclass of ``int`` in Python,
        because ``True`` / ``False`` silently passed to a SQLite
        ``IN`` clause would either filter the wrong user or, worse,
        count as 1 and bias the result.
        """
        if not isinstance(user_ids, list):
            raise TypeError(f"user_ids must be a list[int], got {type(user_ids).__name__}")
        for uid in user_ids:
            if isinstance(uid, bool) or not isinstance(uid, int):
                raise TypeError(
                    f"user_ids must contain only int (got {uid!r} of type {type(uid).__name__})"
                )

    def _int_placeholders(self, n: int) -> str:
        """Return ``"?,?,?,…"`` for ``n`` SQLite placeholders."""
        return ",".join("?" for _ in range(n))

    def get_due_counts_for_users(self, user_ids: List[int]) -> Dict[int, int]:
        """Return ``{user_id: due_count}`` for the given recipients.

        A user with no rows in ``word_stats`` is **omitted** from the
        returned dict; the caller treats that as 0 due words.  One
        ``SELECT user_id, COUNT(*) ... GROUP BY user_id`` query
        regardless of batch size.
        """
        self._check_int_user_ids(user_ids)
        if not user_ids:
            return {}

        placeholders = self._int_placeholders(len(user_ids))
        rows = self.fetch_all(
            f"""
            SELECT ws.user_id, COUNT(*) AS due_count
            FROM word_stats ws
            WHERE ws.user_id IN ({placeholders})
              AND ws.next_review <= datetime('now')
            GROUP BY ws.user_id
            """,
            tuple(user_ids),
        )
        return {uid: int(cnt) for uid, cnt in rows}

    def get_hard_due_counts_for_users(self, user_ids: List[int]) -> Dict[int, int]:
        """Return ``{user_id: hard_due_count}`` for the given recipients.

        Mirrors ``count_hard_due(user_id)`` (phase = 'learning' AND
        next_review <= now) but does it for the whole batch in one
        round-trip.
        """
        self._check_int_user_ids(user_ids)
        if not user_ids:
            return {}

        placeholders = self._int_placeholders(len(user_ids))
        rows = self.fetch_all(
            f"""
            SELECT ws.user_id, COUNT(*) AS hard_count
            FROM word_stats ws
            WHERE ws.user_id IN ({placeholders})
              AND ws.phase = 'learning'
              AND ws.next_review <= datetime('now')
            GROUP BY ws.user_id
            """,
            tuple(user_ids),
        )
        return {uid: int(cnt) for uid, cnt in rows}

    def get_daily_goals_for_users(self, user_ids: List[int]) -> Dict[int, int]:
        """Return ``{user_id: daily_goal}`` for the given recipients.

        Users with no ``user_settings`` row default to **10** (the
        schema default and the value ``get_daily_goal`` already
        returns).  This matches the single-user behaviour of
        ``LearningRepository.get_daily_goal`` so the reminder text is
        unchanged for any user.
        """
        self._check_int_user_ids(user_ids)
        if not user_ids:
            return {}

        placeholders = self._int_placeholders(len(user_ids))
        rows = self.fetch_all(
            f"""
            SELECT user_id, daily_goal
            FROM user_settings
            WHERE user_id IN ({placeholders})
            """,
            tuple(user_ids),
        )
        # Pre-seed every requested user with the schema default so
        # that callers can rely on ``out[uid]`` for *every* uid in
        # ``user_ids``, not just the ones that have a settings row.
        # This mirrors the single-user behaviour of
        # ``LearningRepository.get_daily_goal`` (which also returns
        # 10 when the row is missing).
        out: Dict[int, int] = {int(uid): 10 for uid in user_ids}
        for uid, goal in rows:
            # Treat a NULL / 0 / negative goal the same as "no row"
            # and fall back to the schema default.
            try:
                g = int(goal) if goal is not None else 0
            except (TypeError, ValueError):
                g = 0
            out[int(uid)] = g if g > 0 else 10
        return out

    def get_today_new_counts_for_users(self, user_ids: List[int]) -> Dict[int, int]:
        """Batch the same first-observation counts used by the dashboard."""
        self._check_int_user_ids(user_ids)
        if not user_ids:
            return {}
        placeholders = self._int_placeholders(len(user_ids))
        settings = dict(
            self.fetch_all(
                f"SELECT user_id, timezone_offset_minutes FROM user_settings WHERE user_id IN ({placeholders})",
                tuple(user_ids),
            )
        )
        from config import USER_TIMEZONE_OFFSET_HOURS, USER_TIMEZONE_OFFSET_MINUTES
        from database.time_utils import local_day_bounds

        default = USER_TIMEZONE_OFFSET_HOURS * 60 + USER_TIMEZONE_OFFSET_MINUTES
        groups: Dict[int, List[int]] = {}
        for uid in user_ids:
            offset = settings.get(uid, default)
            if not isinstance(offset, (int, float)) or not -1440 < offset < 1440:
                offset = default
            groups.setdefault(int(offset), []).append(uid)
        out = {}
        for offset, ids in groups.items():
            start, end = local_day_bounds(offset)
            marks = self._int_placeholders(len(ids))
            rows = self.fetch_all(
                f"SELECT user_id, COUNT(*) FROM word_first_seen WHERE user_id IN ({marks}) "
                "AND first_seen_at >= ? AND first_seen_at < ? GROUP BY user_id",
                tuple(ids) + (start, end),
            )
            out.update({int(uid): int(count) for uid, count in rows})
        return out
