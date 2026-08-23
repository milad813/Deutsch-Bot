"""Database package with repository pattern for data access."""

from database.connection import DEFAULT_OWNER_ID, DatabaseConnection, _utc_now
from database.repositories import (
    BookRepository,
    ExtendedWordRepository,
    GrammarRepository,
    LearningRepository,
    LessonRepository,
    StoryRepository,
    UserRepository,
)
from database.schema import SCHEMA_VERSION, ensure_schema
from domain.user import level_from_xp


class Database:
    def __init__(
        self,
        db_name: str = "words.db",
        backup_keep_days: int = 14,
        backup_keep_max: int = 30,
    ):
        self._conn = DatabaseConnection(
            db_name,
            backup_keep_days=backup_keep_days,
            backup_keep_max=backup_keep_max,
        )
        self.words = ExtendedWordRepository(self._conn)
        self.books = BookRepository(self._conn)
        self.lessons = LessonRepository(self._conn)
        self.users = UserRepository(self._conn)
        self.stories = StoryRepository(self._conn)
        self.grammar = GrammarRepository(self._conn)
        self.learning = LearningRepository(self._conn)
        self._ensure_schema()

    @property
    def conn(self):
        return self._conn.conn

    def close(self):
        self._conn.close()

    def backup(self, backup_dir: str = "backups") -> str:
        return self._conn.backup(backup_dir)

    @staticmethod
    def level_from_xp(xp: int) -> tuple:
        """Delegates to the pure domain implementation (domain/user.py)."""
        return level_from_xp(xp)

    def _ensure_schema(self):
        """Create tables/indexes and run additive migrations (see schema.py)."""
        with self._conn.cursor(commit=True) as c:
            ensure_schema(c)


__all__ = [
    "Database",
    "DatabaseConnection",
    "_utc_now",
    "DEFAULT_OWNER_ID",
    "SCHEMA_VERSION",
    "ensure_schema",
]