"""Base repository class for common database operations."""

from typing import List, Optional, Tuple

from database.connection import DatabaseConnection
from database.time_utils import local_day_bounds


class BaseRepository:
    """Base class for all repositories providing common CRUD operations."""

    def __init__(self, connection: DatabaseConnection):
        self._conn = connection

    @property
    def cursor(self):
        """Get database cursor context manager."""
        return self._conn.cursor

    def fetch_one(self, query: str, params: Tuple = ()) -> Optional[Tuple]:
        """Fetch a single row from the database."""
        with self.cursor() as c:
            c.execute(query, params)
            return c.fetchone()

    def fetch_all(self, query: str, params: Tuple = ()) -> List[Tuple]:
        """Fetch all rows from the database."""
        with self.cursor() as c:
            c.execute(query, params)
            return c.fetchall()

    def execute(self, query: str, params: Tuple = (), commit: bool = False) -> None:
        """Execute a database operation."""
        with self.cursor(commit=commit) as c:
            c.execute(query, params)

    def insert(self, query: str, params: Tuple = ()) -> int:
        """Insert a record and return the last inserted ID."""
        with self.cursor(commit=True) as c:
            c.execute(query, params)
            return c.lastrowid

    def timezone_offset(self, user_id: int) -> int:
        from config import USER_TIMEZONE_OFFSET_HOURS, USER_TIMEZONE_OFFSET_MINUTES

        row = self.fetch_one(
            "SELECT timezone_offset_minutes FROM user_settings WHERE user_id=?", (user_id,)
        )
        default = USER_TIMEZONE_OFFSET_HOURS * 60 + USER_TIMEZONE_OFFSET_MINUTES
        offset = row[0] if row and row[0] is not None else default
        return (
            int(offset) if isinstance(offset, (int, float)) and -1440 < offset < 1440 else default
        )

    def day_bounds(self, user_id: int):
        return local_day_bounds(self.timezone_offset(user_id))

    def _not_in_clause(
        self, exclude_ids: Optional[List[int]], column: str = "id"
    ) -> Tuple[str, List[int]]:
        """Generate NOT IN clause for excluding IDs."""
        ids = list(set(exclude_ids or []))
        if not ids:
            return "", []
        placeholders = ",".join("?" for _ in ids)
        return f" AND {column} NOT IN ({placeholders})", ids
