"""Database package with repository pattern for data access."""

from database.connection import DatabaseConnection, _utc_now, DEFAULT_OWNER_ID
from database.repositories import (
    BaseRepository,
    WordRepository,
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
        self.words = WordRepository(self._conn)
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
