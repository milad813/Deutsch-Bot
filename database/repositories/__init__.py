"""Repository classes for data access."""

from database.connection import DatabaseConnection
from database.repositories.base import BaseRepository
from database.repositories.word import WordRepository
from database.repositories.word_extended import ExtendedWordRepository


class BookRepository(BaseRepository):
    """Repository for book-related operations."""

    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def create(self, name: str, level: str = "A1") -> int:
        """Create a new book and return its ID."""
        query = """
            INSERT INTO books (name, level)
            VALUES (?, ?)
        """
        return self.insert(query, (name, level))

    def get_all(self) -> list:
        """Get all books."""
        query = "SELECT id, name, level, created_at FROM books ORDER BY name"
        return self.fetch_all(query)

    def get_by_id(self, book_id: int) -> tuple:
        """Get a book by ID."""
        query = "SELECT id, name, level, created_at FROM books WHERE id = ?"
        return self.fetch_one(query, (book_id,))

    def get_level_by_lesson(self, lesson_id: int) -> str:
        """Get book level by lesson ID."""
        query = """
            SELECT b.level FROM books b
            JOIN lessons l ON b.id = l.book_id
            WHERE l.id = ?
        """
        row = self.fetch_one(query, (lesson_id,))
        return row[0] if row else None


class LessonRepository(BaseRepository):
    """Repository for lesson-related operations."""

    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def create(self, book_id: int, lesson_number: int, title: str = None) -> int:
        """Create a new lesson and return its ID."""
        query = """
            INSERT INTO lessons (book_id, lesson_number, title)
            VALUES (?, ?, ?)
        """
        return self.insert(query, (book_id, lesson_number, title))

    def get_by_book(self, book_id: int) -> list:
        """Get all lessons for a book."""
        query = """
            SELECT id, book_id, lesson_number, title, created_at
            FROM lessons
            WHERE book_id = ?
            ORDER BY lesson_number
        """
        return self.fetch_all(query, (book_id,))

    def get_by_id(self, lesson_id: int) -> tuple:
        """Get a lesson by ID."""
        query = """
            SELECT id, book_id, lesson_number, title, created_at
            FROM lessons
            WHERE id = ?
        """
        return self.fetch_one(query, (lesson_id,))

    def get_book_id(self, lesson_id: int) -> int:
        """Get book ID for a lesson."""
        query = "SELECT book_id FROM lessons WHERE id = ?"
        row = self.fetch_one(query, (lesson_id,))
        return row[0] if row else None

    def update_title(self, lesson_id: int, title: str) -> None:
        """Update lesson title if empty."""
        query = """
            UPDATE lessons
            SET title = ?
            WHERE id = ? AND (title IS NULL OR title = '')
        """
        self.execute(query, (title, lesson_id), commit=True)


class UserRepository(BaseRepository):
    """Repository for user-related operations."""

    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def get_stats(self, user_id: int) -> dict:
        """Get user quiz statistics."""
        query = """
            SELECT correct_answers, total_answers
            FROM user_stats
            WHERE user_id = ?
        """
        row = self.fetch_one(query, (user_id,))
        if not row:
            return {"correct": 0, "total": 0}
        return {"correct": row[0], "total": row[1]}

    def get_quiz_stats(self, user_id: int) -> tuple:
        """Get quiz stats as tuple (correct, total)."""
        stats = self.get_stats(user_id)
        return (stats["correct"], stats["total"])

    def get_progress(self, user_id: int) -> dict:
        """Get user progress (xp, streak, last_active_date)."""
        query = """
            SELECT xp, streak, last_active_date
            FROM user_progress
            WHERE user_id = ?
        """
        row = self.fetch_one(query, (user_id,))
        if row:
            return {
                "xp": row[0] or 0,
                "streak": row[1] or 0,
                "last_active_date": row[2],
            }
        return {"xp": 0, "streak": 0, "last_active_date": None}

    def update_quiz_stats(self, user_id: int, is_correct: bool) -> None:
        """Update user quiz statistics."""
        correct_inc = 1 if is_correct else 0
        query = """
            INSERT INTO user_stats (user_id, correct_answers, total_answers)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
            correct_answers = correct_answers + ?,
            total_answers = total_answers + 1
        """
        self.execute(query, (user_id, correct_inc, correct_inc), commit=True)

    def get_settings(self, user_id: int) -> dict:
        """Get user settings."""
        query = """
            SELECT preferred_level FROM user_settings
            WHERE user_id = ?
        """
        row = self.fetch_one(query, (user_id,))
        return {"preferred_level": row[0]} if row else {}

    def update_setting(self, user_id: int, preferred_level: str) -> None:
        """Update user setting."""
        query = """
            INSERT INTO user_settings (user_id, preferred_level)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
            preferred_level = excluded.preferred_level
        """
        self.execute(query, (user_id, preferred_level), commit=True)

    def record_activity(self, user_id: int, xp_gain: int) -> dict:
        """Record user activity and return updated stats."""
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        query = """
            INSERT INTO user_activity (user_id, date, xp_gain)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET
            xp_gain = xp_gain + ?
        """
        self.execute(query, (user_id, today, xp_gain, xp_gain), commit=True)

        # Get updated stats
        stats_query = """
            SELECT SUM(xp_gain) as daily_xp, COUNT(*) as streak
            FROM user_activity
            WHERE user_id = ?
            GROUP BY user_id
        """
        row = self.fetch_one(stats_query, (user_id,))

        return {
            "daily_xp": row[0] if row else 0,
            "level": self._level_from_xp(row[0] if row else 0),
        }

    @staticmethod
    def _level_from_xp(xp: int) -> int:
        """Calculate level from XP."""
        return int(xp / 100) + 1


class GrammarRepository(BaseRepository):
    """Repository for grammar point operations."""

    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def add(
        self,
        lesson_id: int,
        topic_de: str,
        topic_fa: str,
        explanation_de: str,
        explanation_fa: str,
        examples: str = None,
    ) -> int:
        """Add a grammar point."""
        query = """
            INSERT INTO grammar_points
            (lesson_id, topic_de, topic_fa, explanation_de, explanation_fa, examples)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        return self.insert(
            query,
            (lesson_id, topic_de, topic_fa, explanation_de, explanation_fa, examples),
        )

    def get_by_lesson(self, lesson_id: int) -> list:
        """Get all grammar points for a lesson."""
        query = """
            SELECT id, lesson_id, topic_de, topic_fa, explanation_de, 
                   explanation_fa, examples, created_at
            FROM grammar_points
            WHERE lesson_id = ?
        """
        return self.fetch_all(query, (lesson_id,))

    def get_by_id(self, gid: int) -> tuple:
        """Get a grammar point by ID."""
        query = """
            SELECT id, lesson_id, topic_de, topic_fa, explanation_de,
                   explanation_fa, examples, created_at
            FROM grammar_points
            WHERE id = ?
        """
        return self.fetch_one(query, (gid,))


class StoryRepository(BaseRepository):
    """Repository for story operations."""

    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def add(
        self,
        lesson_id: int,
        title_de: str,
        title_fa: str,
        text_de: str,
        text_fa: str,
        audio_url: str = None,
    ) -> int:
        """Add a story."""
        query = """
            INSERT INTO stories
            (lesson_id, title_de, title_fa, text_de, text_fa, audio_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        return self.insert(
            query, (lesson_id, title_de, title_fa, text_de, text_fa, audio_url)
        )

    def get_by_lesson(self, lesson_id: int) -> list:
        """Get all stories for a lesson."""
        query = """
            SELECT id, lesson_id, title_de, title_fa, text_de, text_fa,
                   audio_url, created_at
            FROM stories
            WHERE lesson_id = ?
        """
        return self.fetch_all(query, (lesson_id,))

    def get_by_id(self, story_id: int) -> tuple:
        """Get a story by ID."""
        query = """
            SELECT id, lesson_id, title_de, title_fa, text_de, text_fa,
                   audio_url, created_at
            FROM stories
            WHERE id = ?
        """
        return self.fetch_one(query, (story_id,))

    def get_count(self, lesson_id: int) -> int:
        """Get story count for a lesson."""
        query = "SELECT COUNT(*) FROM stories WHERE lesson_id = ?"
        row = self.fetch_one(query, (lesson_id,))
        return row[0] if row else 0


__all__ = [
    "BaseRepository",
    "BookRepository",
    "LessonRepository",
    "UserRepository",
    "WordRepository",
    "ExtendedWordRepository",
    "GrammarRepository",
    "StoryRepository",
]
