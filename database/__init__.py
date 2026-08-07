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
