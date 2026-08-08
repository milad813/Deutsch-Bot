"""Database connection management and migrations."""

import sqlite3
import os
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_OWNER_ID = 1


def _utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class DatabaseConnection:
    """Manages SQLite database connection and schema migrations."""

    def __init__(self, db_name: str = "words.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self._setup_connection()

    def _setup_connection(self) -> None:
        """Configure SQLite connection with optimal settings."""
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")

    @contextmanager
    def cursor(self, commit: bool = False):
        """Context manager for database cursors with automatic cleanup."""
        cur = self.conn.cursor()
        try:
            yield cur
            if commit:
                self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    def close(self) -> None:
        """Close database connection."""
        try:
            self.conn.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error("Error closing database: %s", e)

    def backup(self, backup_dir: str = "backups") -> str:
        """Create a backup of the database."""
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"words_{timestamp}.db")

        dest = sqlite3.connect(backup_path)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()

        return backup_path
