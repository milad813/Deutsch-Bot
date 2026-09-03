"""Repository classes for data access."""

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from database.connection import DatabaseConnection
from database.repositories.base import BaseRepository
from database.repositories.learning import LearningRepository
from database.repositories.word_extended import ExtendedWordRepository


class BookRepository(BaseRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def create(self, name: str, level: str = "A1") -> int:
        try:
            return self.insert(
                "INSERT INTO books (name, level) VALUES (?, ?)", (name, level)
            )
        except sqlite3.IntegrityError:
            row = self.fetch_one("SELECT id FROM books WHERE name = ?", (name,))
            return row[0] if row else 0

    def get_all(self) -> list:
        return self.fetch_all("SELECT id, name, level FROM books ORDER BY name")

    def get_by_id(self, book_id: int) -> tuple:
        return self.fetch_one(
            "SELECT id, name, level FROM books WHERE id = ?", (book_id,)
        )

    def get_level_by_lesson(self, lesson_id: int) -> Optional[str]:
        row = self.fetch_one(
            """SELECT b.level FROM books b JOIN lessons l ON b.id = l.book_id WHERE l.id = ?""",
            (lesson_id,),
        )
        return row[0] if row else None

    def get_count(self) -> int:
        """Return the total number of books in the catalogue.

        Used by the admin ``/status`` view. Returns 0 for an empty or
        missing table so the admin page never crashes mid-render.
        """
        import sqlite3

        try:
            row = self.fetch_one("SELECT COUNT(*) FROM books")
        except sqlite3.OperationalError:
            return 0
        return row[0] if row else 0


class LessonRepository(BaseRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def create(self, book_id: int, lesson_number: int, title: str = None) -> int:
        try:
            return self.insert(
                "INSERT INTO lessons (book_id, lesson_number, title) VALUES (?, ?, ?)",
                (book_id, lesson_number, title),
            )
        except sqlite3.IntegrityError:
            row = self.fetch_one(
                "SELECT id FROM lessons WHERE book_id = ? AND lesson_number = ?",
                (book_id, lesson_number),
            )
            return row[0] if row else 0

    def get_by_book(self, book_id: int) -> list:
        return self.fetch_all(
            "SELECT id, lesson_number, title FROM lessons WHERE book_id = ? ORDER BY lesson_number",
            (book_id,),
        )

    def get_by_id(self, lesson_id: int) -> tuple:
        return self.fetch_one(
            "SELECT id, lesson_number, title FROM lessons WHERE id = ?", (lesson_id,)
        )

    def get_book_id(self, lesson_id: int) -> Optional[int]:
        row = self.fetch_one("SELECT book_id FROM lessons WHERE id = ?", (lesson_id,))
        return row[0] if row else None

    def update_title(self, lesson_id: int, title: str) -> None:
        self.execute(
            "UPDATE lessons SET title = ? WHERE id = ? AND (title IS NULL OR title = '')",
            (title, lesson_id),
            commit=True,
        )

    def get_count(self) -> int:
        """Return the total number of lessons in the catalogue.

        Used by the admin ``/status`` view. Returns 0 for an empty or
        missing table so the admin page never crashes mid-render.
        """
        import sqlite3

        try:
            row = self.fetch_one("SELECT COUNT(*) FROM lessons")
        except sqlite3.OperationalError:
            return 0
        return row[0] if row else 0


class UserRepository(BaseRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def _today_local(self) -> str:
        from config import USER_TIMEZONE_OFFSET_HOURS, USER_TIMEZONE_OFFSET_MINUTES

        tz = timezone(
            timedelta(
                hours=USER_TIMEZONE_OFFSET_HOURS, minutes=USER_TIMEZONE_OFFSET_MINUTES
            )
        )
        return datetime.now(tz).strftime("%Y-%m-%d")

    def get_stats(self, user_id: int) -> dict:
        row = self.fetch_one(
            "SELECT correct_answers, total_answers FROM user_stats WHERE user_id = ?",
            (user_id,),
        )
        if not row:
            return {"correct": 0, "total": 0}
        return {"correct": row[0], "total": row[1]}

    def get_quiz_stats(self, user_id: int) -> tuple:
        s = self.get_stats(user_id)
        return (s["correct"], s["total"])

    def get_progress(self, user_id: int) -> dict:
        row = self.fetch_one(
            "SELECT xp, streak, last_active_date FROM user_progress WHERE user_id = ?",
            (user_id,),
        )
        if row:
            return {
                "xp": row[0] or 0,
                "streak": row[1] or 0,
                "last_active_date": row[2],
            }
        return {"xp": 0, "streak": 0, "last_active_date": None}

    def update_quiz_stats(self, user_id: int, is_correct: bool) -> None:
        correct_inc = 1 if is_correct else 0
        self.execute(
            """INSERT INTO user_stats (user_id, correct_answers, total_answers) VALUES (?, ?, 1)
                        ON CONFLICT(user_id) DO UPDATE SET correct_answers = correct_answers + ?,
                        total_answers = total_answers + 1""",
            (user_id, correct_inc, correct_inc),
            commit=True,
        )

    def get_settings(self, user_id: int) -> dict:
        row = self.fetch_one(
            "SELECT preferred_level, daily_goal, reminders_enabled, "
            "timezone_offset_minutes FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        if not row:
            return {}
        return {
            "preferred_level": row[0] or "A1",
            "daily_goal": row[1] if row[1] else 10,
            "reminders_enabled": bool(row[2]) if row[2] is not None else False,
            "timezone_offset_minutes": row[3] if row[3] is not None else 210,
        }

    def update_setting(self, user_id: int, preferred_level: str) -> None:
        self.execute(
            """INSERT INTO user_settings (user_id, preferred_level) VALUES (?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET preferred_level = excluded.preferred_level""",
            (user_id, preferred_level),
            commit=True,
        )

    def register_user(
        self, user_id: int, username=None, first_name=None, last_name=None
    ):
        self.execute(
            """INSERT INTO users (user_id, username, first_name, last_name, last_active_at)
                        VALUES (?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(user_id) DO UPDATE SET username = excluded.username,
                        first_name = excluded.first_name, last_name = excluded.last_name,
                        last_active_at = datetime('now')""",
            (user_id, username, first_name, last_name),
            commit=True,
        )

    def get_all_users(self) -> List[Tuple]:
        return self.fetch_all(
            """SELECT user_id, username, first_name, last_name, joined_at, last_active_at
                                 FROM users ORDER BY last_active_at DESC"""
        )

    def get_user_count(self) -> int:
        row = self.fetch_one("SELECT COUNT(*) FROM users")
        return row[0] if row else 0

    def get_active_user_count(self, days: int = 7) -> int:
        row = self.fetch_one(
            "SELECT COUNT(*) FROM users WHERE last_active_at >= datetime('now', ?)",
            (f"-{days} days",),
        )
        return row[0] if row else 0

    # ─────────────────────────────
    # Daily reminder opt-in (Phase 0 hardening)
    # ─────────────────────────────
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
        current = self.get_reminders_enabled(user_id)
        new_value = not current
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

    # ─────────────────────────────────────────────────────────────────
    # Batched reminder stats (Phase 1, item 5)
    # ─────────────────────────────────────────────────────────────────
    # The daily reminder job used to run FOUR queries per recipient
    # (due count + hard count + daily goal + today-new count). With a
    # few hundred active users that meant a few hundred round-trips
    # through ``asyncio.to_thread`` and the SQLite write lock. The
    # four helpers below let the job process a batch of recipients in
    # a single query each, so the total work is 4 queries per batch
    # instead of 4·N queries per reminder run.
    #
    # Shared contract:
    #   * ``user_ids`` MUST be a list of int.  Empty list short-
    #     circuits to an empty dict (no SQL is executed) so a "no
    #     opted-in users today" job costs zero DB calls.
    #   * The returned dict only contains entries for users that
    #     actually have data; users with no rows are omitted (the
    #     caller treats absence as the default — see Task 5 spec).
    #   * Inactive / opted-out filtering is the caller's job — these
    #     methods are pure aggregators.
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
            raise TypeError(
                f"user_ids must be a list[int], got {type(user_ids).__name__}"
            )
        for uid in user_ids:
            if isinstance(uid, bool) or not isinstance(uid, int):
                raise TypeError(
                    f"user_ids must contain only int (got {uid!r} of type "
                    f"{type(uid).__name__})"
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

    def get_hard_due_counts_for_users(
        self, user_ids: List[int]
    ) -> Dict[int, int]:
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

    def get_today_new_counts_for_users(
        self, user_ids: List[int]
    ) -> Dict[int, int]:
        """Return ``{user_id: today_new_count}`` for the given recipients.

        "Today" is computed in the configured user-local timezone,
        matching ``LearningRepository.get_today_new_words_count``.  We
        do the timezone math in Python (one datetime) and pass the
        UTC cut-off string to SQLite; the GROUP BY is the only
        difference vs the single-user path.
        """
        self._check_int_user_ids(user_ids)
        if not user_ids:
            return {}

        # Local-day boundary -> UTC timestamp string. Mirrors the
        # per-user implementation so a migration from one to the
        # other does not change a single digit in the reminder text.
        from config import (
            USER_TIMEZONE_OFFSET_HOURS,
            USER_TIMEZONE_OFFSET_MINUTES,
        )

        tz = timezone(
            timedelta(
                hours=USER_TIMEZONE_OFFSET_HOURS,
                minutes=USER_TIMEZONE_OFFSET_MINUTES,
            )
        )
        now_local = datetime.now(tz)
        today_start_local = now_local.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_start_utc = today_start_local.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        placeholders = self._int_placeholders(len(user_ids))
        rows = self.fetch_all(
            f"""
            SELECT user_id, COUNT(DISTINCT word_id) AS new_count
            FROM word_stats
            WHERE user_id IN ({placeholders})
              AND last_reviewed >= ?
            GROUP BY user_id
            """,
            tuple(user_ids) + (today_start_utc,),
        )
        return {int(uid): int(cnt) for uid, cnt in rows}

    def reset_user_progress(self, user_id: int):
        for sql in [
            "DELETE FROM word_stats WHERE user_id = ?",
            "DELETE FROM word_skills WHERE user_id = ?",
            "DELETE FROM mistakes WHERE user_id = ?",
            "DELETE FROM mistake_stats WHERE user_id = ?",
            "DELETE FROM story_progress WHERE user_id = ?",
            "DELETE FROM grammar_progress WHERE user_id = ?",
            "DELETE FROM user_stats WHERE user_id = ?",
            "DELETE FROM user_progress WHERE user_id = ?",
        ]:
            self.execute(sql, (user_id,), commit=True)

    def record_activity(self, user_id: int, xp_gain: int) -> Dict:
        today = self._today_local()
        r = self.fetch_one(
            "SELECT xp, streak, last_active_date FROM user_progress WHERE user_id=?",
            (user_id,),
        )
        if r is None:
            xp = max(0, xp_gain)
            streak = 1
            self.execute(
                "INSERT INTO user_progress(user_id, xp, streak, last_active_date) VALUES(?,?,?,?)",
                (user_id, xp, streak, today),
                commit=True,
            )
        else:
            xp = (r[0] or 0) + max(0, xp_gain)
            old_streak = r[1] or 0
            last = r[2]
            if last == today:
                streak = old_streak if old_streak > 0 else 1
            elif last is None:
                streak = 1
            else:
                try:
                    gap = (
                        datetime.strptime(today, "%Y-%m-%d")
                        - datetime.strptime(last, "%Y-%m-%d")
                    ).days
                    streak = (old_streak + 1) if gap == 1 else 1
                except Exception:
                    streak = 1
            self.execute(
                "UPDATE user_progress SET xp=?, streak=?, last_active_date=? WHERE user_id=?",
                (xp, streak, today, user_id),
                commit=True,
            )
        return {"xp": xp, "streak": streak}


class StoryRepository(BaseRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def add(
        self,
        lesson_id,
        title_de,
        title_fa,
        text_de,
        text_fa,
        target_word_ids=None,
        questions_json=None,
        level=None,
    ) -> int:
        return self.insert(
            """INSERT INTO stories (lesson_id, title_de, title_fa, text_de, text_fa,
                            target_word_ids, questions_json, level) VALUES (?,?,?,?,?,?,?,?)""",
            (
                lesson_id,
                title_de,
                title_fa,
                text_de,
                text_fa,
                target_word_ids,
                questions_json,
                level,
            ),
        )

    def get_by_lesson(self, lesson_id: int) -> list:
        return self.fetch_all(
            """SELECT id, lesson_id, title_de, title_fa, text_de, text_fa,
                                 target_word_ids, questions_json, level, created_at
                                 FROM stories WHERE lesson_id = ? ORDER BY id""",
            (lesson_id,),
        )

    def get_by_id(self, story_id: int) -> Optional[Dict]:
        row = self.fetch_one(
            """SELECT id, lesson_id, title_de, title_fa, text_de, text_fa,
                                target_word_ids, questions_json, level FROM stories WHERE id = ?""",
            (story_id,),
        )
        if not row:
            return None
        return {
            "id": row[0],
            "lesson_id": row[1],
            "title_de": row[2],
            "title_fa": row[3],
            "text_de": row[4],
            "text_fa": row[5],
            "target_word_ids": row[6],
            "questions_json": row[7],
            "level": row[8],
        }

    def get_count(self, lesson_id: int) -> int:
        row = self.fetch_one(
            "SELECT COUNT(*) FROM stories WHERE lesson_id = ?", (lesson_id,)
        )
        return row[0] if row else 0


class GrammarRepository(BaseRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def upsert(
        self,
        lesson_id,
        topic_key,
        title_fa,
        level,
        explanation_fa,
        rule_de,
        examples_json,
        exercises_json,
        certainty,
        note,
    ) -> int:
        row = self.fetch_one(
            "SELECT id FROM grammar_points WHERE lesson_id=? AND topic_key=?",
            (lesson_id, topic_key),
        )
        if row:
            gid = row[0]
            self.execute(
                """UPDATE grammar_points SET title_fa=?, level=?, explanation_fa=?, rule_de=?,
                            examples_json=?, exercises_json=?, certainty=?, note=? WHERE id=?""",
                (
                    title_fa,
                    level,
                    explanation_fa,
                    rule_de,
                    examples_json,
                    exercises_json,
                    certainty,
                    note,
                    gid,
                ),
                commit=True,
            )
            return gid
        return self.insert(
            """INSERT INTO grammar_points (lesson_id, topic_key, title_fa, level, explanation_fa,
                            rule_de, examples_json, exercises_json, certainty, note)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                lesson_id,
                topic_key,
                title_fa,
                level,
                explanation_fa,
                rule_de,
                examples_json,
                exercises_json,
                certainty,
                note,
            ),
        )

    def get_by_lesson(self, lesson_id) -> List[Dict]:
        rows = self.fetch_all(
            "SELECT id, topic_key, title_fa FROM grammar_points WHERE lesson_id=? ORDER BY id",
            (lesson_id,),
        )
        return [{"id": r[0], "topic_key": r[1], "title_fa": r[2]} for r in rows]

    def get_by_id(self, gid) -> Optional[Dict]:
        r = self.fetch_one(
            """SELECT id, lesson_id, topic_key, title_fa, level, explanation_fa,
                              rule_de, examples_json, exercises_json, certainty, note
                              FROM grammar_points WHERE id=?""",
            (gid,),
        )
        if not r:
            return None
        return {
            "id": r[0],
            "lesson_id": r[1],
            "topic_key": r[2],
            "title_fa": r[3],
            "level": r[4],
            "explanation_fa": r[5],
            "rule_de": r[6],
            "examples_json": r[7],
            "exercises_json": r[8],
            "certainty": r[9],
            "note": r[10],
        }


__all__ = [
    "BaseRepository",
    "BookRepository",
    "LessonRepository",
    "UserRepository",
    "ExtendedWordRepository",
    "StoryRepository",
    "LearningRepository",
    "GrammarRepository",
]
