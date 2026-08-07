"""Database package with repository pattern for data access."""

from database.connection import DatabaseConnection, _utc_now, DEFAULT_OWNER_ID
from database.repositories import (
    BaseRepository,
    WordRepository,
    ExtendedWordRepository,
    BookRepository,
    LessonRepository,
    UserRepository,
    GrammarRepository,
    StoryRepository
)


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
        self.grammar = GrammarRepository(self._conn)
        self.stories = StoryRepository(self._conn)
        
    @property
    def conn(self):
        """Expose connection for backward compatibility."""
        return self._conn.conn
        
    def close(self):
        """Close database connection."""
        self._conn.close()
    
    # Backward compatibility methods - delegate to repositories
    def get_all_books(self) -> list:
        """Get all books (backward compatibility)."""
        return self.books.get_all()
    
    def get_due_word_count(self, user_id: int) -> int:
        """Get count of words due for review (backward compatibility)."""
        return self.words.get_due_count(user_id)
    
    def get_hard_due_word_objects(self, user_id: int, limit: int = 20, exclude_ids=None):
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
    
    def get_lesson(self, lesson_id: int) -> dict:
        """Get lesson by ID (backward compatibility)."""
        return self.lessons.get_by_id(lesson_id)
    
    def get_book_id_by_lesson(self, lesson_id: int) -> int:
        """Get book ID for a lesson (backward compatibility)."""
        return self.lessons.get_book_id(lesson_id)
    
    def get_words_by_lesson_full(self, lesson_id: int) -> list:
        """Get words for a lesson with full details (backward compatibility)."""
        return self.words.get_by_lesson_full(lesson_id)
    
    def update_user_setting(self, user_id: int, preferred_level: str) -> None:
        """Update user setting (backward compatibility)."""
        self.users.update_setting(user_id, preferred_level)
    
    def get_user_settings(self, user_id: int) -> dict:
        """Get user settings (backward compatibility)."""
        return self.users.get_settings(user_id)
    
    @staticmethod
    def level_from_xp(xp: int) -> tuple:
        """Calculate level from XP (backward compatibility)."""
        if xp < 100:
            return "A1", "مبتدی", 100 - xp
        elif xp < 300:
            return "A2", "پایه‌ای", 300 - xp
        elif xp < 600:
            return "B1", "متوسط", 600 - xp
        elif xp < 900:
            return "B2", "بالای متوسط", 900 - xp
        else:
            return "C1", "پیشرفته", 0
        

__all__ = [
    "Database",
    "DatabaseConnection",
    "_utc_now",
    "DEFAULT_OWNER_ID",
    "BaseRepository",
    "WordRepository",
    "BookRepository",
    "LessonRepository",
    "UserRepository",
    "GrammarRepository",
    "StoryRepository",
]
