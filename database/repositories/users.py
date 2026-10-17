"""User accounts, progress and settings."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
from database.connection import DatabaseConnection

from database.repositories.reminders import ReminderRepository


class UserRepository(ReminderRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def _today_local(self, user_id: int) -> str:
        tz = timezone(timedelta(minutes=self.timezone_offset(user_id)))
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

    def register_user(self, user_id: int, username=None, first_name=None, last_name=None):
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

    def reset_user_progress(self, user_id: int):
        """Reset learning state atomically while retaining settings and LLM quotas."""
        tables = (
            "word_stats",
            "word_skills",
            "mistakes",
            "mistake_stats",
            "story_progress",
            "grammar_progress",
            "user_stats",
            "user_progress",
            "word_first_seen",
            "ltr_attempts",
            "ltr_finalizations",
        )
        with self._conn.transaction():
            for table in tables:
                self.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,), commit=True)

    def record_activity(self, user_id: int, xp_gain: int) -> Dict:
        with self._conn.transaction():
            today = self._today_local(user_id)
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
