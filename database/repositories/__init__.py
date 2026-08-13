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
            "SELECT preferred_level, daily_goal FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        if not row:
            return {}
        return {
            "preferred_level": row[0] or "A1",
            "daily_goal": row[1] if row[1] else 10,
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
