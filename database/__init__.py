"""Database package with repository pattern for data access."""

from database.connection import DEFAULT_OWNER_ID, DatabaseConnection, _utc_now
from database.repositories import (BaseRepository, BookRepository,
                                   ExtendedWordRepository, LearningRepository,
                                   LessonRepository, StoryRepository,
                                   UserRepository)

# Import legacy database for fallback methods
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from database import db_legacy


class Database:
    """Legacy Database class for backward compatibility.

    This class wraps the new repository-based architecture to maintain
    compatibility with existing code during migration.
    """

    def __init__(self, db_name: str = "words.db"):
        self._conn = DatabaseConnection(db_name)
        self.words = ExtendedWordRepository(self._conn)
        self.books = BookRepository(self._conn)
        self.lessons = LessonRepository(self._conn)
        self.users = UserRepository(self._conn)
        self.stories = StoryRepository(self._conn)
        
        # Create legacy db instance for fallback methods
        self._legacy = db_legacy.Database(db_name)

        # New unified learning repository
        self.learning = LearningRepository(self._conn)
        self._ensure_learning_schema()

    @property
    def conn(self):
        """Expose connection for backward compatibility."""
        return self._conn.conn

    def close(self):
        """Close database connections."""
        try:
            self._conn.close()
        finally:
            if hasattr(self, "_legacy"):
                self._legacy.close()

    def _ensure_learning_schema(self):
        """Create phase-2 learning tables if they do not exist."""
        with self._conn.cursor(commit=True) as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS word_skills (
                user_id INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                skill_type TEXT NOT NULL,
                correct_count INTEGER DEFAULT 0,
                wrong_count INTEGER DEFAULT 0,
                last_reviewed TIMESTAMP,
                last_wrong_at TIMESTAMP,
                PRIMARY KEY (user_id, word_id, skill_type)
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS mistakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                word_id INTEGER,
                grammar_point_id INTEGER,
                story_id INTEGER,
                skill_type TEXT,
                quiz_type TEXT,
                user_answer TEXT,
                correct_answer TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS mistake_stats (
                user_id INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                skill_type TEXT NOT NULL,
                wrong_count INTEGER DEFAULT 0,
                last_wrong_at TIMESTAMP,
                resolved_at TIMESTAMP,
                PRIMARY KEY (user_id, word_id, skill_type)
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS grammar_progress (
                user_id INTEGER NOT NULL,
                grammar_point_id INTEGER NOT NULL,
                correct_count INTEGER DEFAULT 0,
                wrong_count INTEGER DEFAULT 0,
                last_reviewed TIMESTAMP,
                next_review TIMESTAMP,
                PRIMARY KEY (user_id, grammar_point_id)
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS story_progress (
                user_id INTEGER NOT NULL,
                story_id INTEGER NOT NULL,
                correct_count INTEGER DEFAULT 0,
                wrong_count INTEGER DEFAULT 0,
                last_reviewed TIMESTAMP,
                PRIMARY KEY (user_id, story_id)
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS llm_examples (
                word_id INTEGER NOT NULL,
                level TEXT NOT NULL,
                example_de TEXT,
                example_fa TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(word_id, level)
            )
            """)

            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_word_skills_user_word "
                "ON word_skills(user_id, word_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_mistakes_user "
                "ON mistakes(user_id, created_at)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_mistake_stats_user "
                "ON mistake_stats(user_id, last_wrong_at)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_grammar_progress_user "
                "ON grammar_progress(user_id, next_review)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_story_progress_user "
                "ON story_progress(user_id, story_id)"
            )
            for migration_sql in ("ALTER TABLE word_skills ADD COLUMN correct_streak INTEGER DEFAULT 0",):
                try:
                    c.execute(migration_sql)
                except Exception:
                    pass
    def __getattr__(self, name):
        """Fallback to legacy database for missing methods."""
        return getattr(self._legacy, name)

    # Backward compatibility methods - delegate to repositories
    def get_all_books(self) -> list:
        """Get all books (backward compatibility)."""
        return self.books.get_all()

    def get_due_word_count(self, user_id: int) -> int:
        """Get count of words due for review (backward compatibility)."""
        return self.words.get_due_count(user_id)

    def get_hard_due_word_objects(
        self, user_id: int, limit: int = 20, exclude_ids=None
    ):
        """Get hard due words (backward compatibility)."""
        return self.words.get_hard_due(user_id, limit, exclude_ids)

    def get_due_word_objects(
        self,
        user_id: int,
        limit: int = 20,
        lesson_id: int = None,
        exclude_ids=None,
    ):
        """Get words due for review (backward compatibility)."""
        return self.words.get_due(user_id, limit, lesson_id, exclude_ids)

    def get_user_progress(self, user_id: int) -> dict:
        """Get user progress (backward compatibility)."""
        return self.users.get_progress(user_id)

    def count_hard_due_words(self, user_id: int) -> int:
        """Count hard words due for review (backward compatibility)."""
        return self.words.count_hard_due(user_id)

    def get_words_due_today(self, user_id: int) -> list:
        """Get words due today (backward compatibility)."""
        return self.words.get_due_today(user_id)

    def get_quiz_stats(self, user_id: int) -> tuple:
        """Get quiz statistics (backward compatibility)."""
        return self.users.get_quiz_stats(user_id)

    def get_word_count(self) -> int:
        """Get total word count (backward compatibility)."""
        return self.words.get_count()

    def get_lessons_by_book(self, book_id: int) -> list:
        """Get lessons by book (backward compatibility)."""
        return self.lessons.get_by_book(book_id)

    def get_book_id_by_lesson(self, lesson_id: int) -> int:
        """Get book ID for a lesson (backward compatibility)."""
        return self.lessons.get_book_id(lesson_id)

    def get_words_by_lesson_full(self, lesson_id: int) -> list:
        """Get words for a lesson with full details (backward compatibility)."""
        return self.words.get_by_lesson_full(lesson_id)

    def get_flashcard_words(
        self, user_id: int, lesson_id: int = None, limit: int = 20,
        include_new: bool = False, new_limit: int = 5, exclude_ids: list = None
    ):
        """Get words for flashcard review (backward compatibility)."""
        return self.words.get_flashcard_words(
            user_id=user_id,
            lesson_id=lesson_id,
            limit=limit,
            include_new=include_new,
            new_limit=new_limit,
            exclude_ids=exclude_ids,
        )

    def get_nouns_with_article_objects(
        self,
        lesson_id: int = None,
        limit: int = 100,
        exclude_ids: list = None,
    ):
        """Get nouns with articles (backward compatibility)."""
        return self.words.get_nouns_with_article(
            lesson_id=lesson_id,
            limit=limit,
            exclude_ids=exclude_ids,
        )

    def update_user_setting(self, user_id: int, preferred_level: str) -> None:
        """Update user setting (backward compatibility)."""
        self.users.update_setting(user_id, preferred_level)

    def get_user_settings(self, user_id: int) -> dict:
        """Get user settings (backward compatibility)."""
        return self.users.get_settings(user_id)

    @staticmethod
    def level_from_xp(xp: int) -> tuple:
        """Calculate level from XP (backward compatibility).
        
        Returns: (level_number, current_xp_in_level, xp_needed_for_next_level)
        All values are integers for progress_bar compatibility.
        """
        level = (xp // 100) + 1
        current = xp % 100
        needed = 100
        return level, current, needed

    # ─────────────────────────────
    # Phase C: reduce legacy fallbacks
    # ─────────────────────────────

    def get_new_word_objects(
        self,
        user_id: int,
        lesson_id: int = None,
        limit: int = 20,
        exclude_ids=None,
    ):
        """Get new words via repository."""
        return self.words.get_new_word_objects(
            user_id=user_id,
            lesson_id=lesson_id,
            limit=limit,
            exclude_ids=exclude_ids,
        )

    def get_weak_word_objects(
        self,
        user_id: int,
        limit: int = 20,
        exclude_ids=None,
    ):
        """Get weak words via repository."""
        return self.words.get_weak(
            user_id=user_id,
            limit=limit,
            exclude_ids=exclude_ids,
        )

    def get_weak_word_count(self, user_id: int) -> int:
        """Get weak word count via repository."""
        return self.words.get_weak_count(user_id)

    def get_random_word_object(
        self,
        lesson_id: int = None,
        exclude_ids=None,
    ):
        """Get random word via repository."""
        return self.words.get_random(
            lesson_id=lesson_id,
            exclude_ids=exclude_ids,
        )

    def get_words_with_example_objects(
        self,
        lesson_id: int = None,
        exclude_ids=None,
    ):
        """Get words with examples via repository."""
        return self.words.get_with_examples(
            lesson_id=lesson_id,
            exclude_ids=exclude_ids,
        )

    def get_word_count_by_lesson(self, lesson_id: int) -> int:
        """Get word count by lesson via repository."""
        return self.words.get_count_by_lesson(lesson_id)

    def get_word_stats_full(self, user_id: int, word_id: int):
        """Get full word stats via repository."""
        return self.words.get_stats_full(user_id, word_id)

    def update_word_stats_fsrs(
        self,
        user_id: int,
        word_id: int,
        correct: int,
        wrong: int,
        ease_factor: float,
        interval_days: int,
        srs_level: int,
        last_review: str,
        next_review: str,
        phase: str = "review",
        stability: float = 0.0,
        difficulty: float = 0.0,
    ):
        """Update FSRS stats via repository."""
        return self.words.update_stats_fsrs(
            user_id=user_id,
            word_id=word_id,
            correct=correct,
            wrong=wrong,
            ease_factor=ease_factor,
            interval_days=interval_days,
            srs_level=srs_level,
            last_review=last_review,
            next_review=next_review,
            phase=phase,
            stability=stability,
            difficulty=difficulty,
        )

    def get_weekly_stats(self, user_id: int):
        """Get weekly stats via learning repository."""
        return self.learning.get_weekly_stats(user_id)

    def get_today_activity_count(self, user_id: int) -> int:
        """Get today's activity count via learning repository."""
        return self.learning.get_today_activity_count(user_id)

    def get_daily_goal(self, user_id: int) -> int:
        """Get daily goal via learning repository."""
        return self.learning.get_daily_goal(user_id)

    def set_daily_goal(self, user_id: int, goal: int) -> None:
        """Set daily goal via learning repository."""
        self.learning.set_daily_goal(user_id, goal)

    def get_mistake_word_count(self, user_id: int) -> int:
        """Get unresolved mistake word count via learning repository."""
        return self.learning.get_mistake_word_count(user_id)

__all__ = [
    "Database",
    "DatabaseConnection",
    "_utc_now",
    "DEFAULT_OWNER_ID",
    "BaseRepository",
    "BookRepository",
    "LessonRepository",
    "UserRepository",
    "StoryRepository",
    "ExtendedWordRepository",
    "LearningRepository",
]
