"""Database connection management with thread safety."""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from threading import Lock

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """Thread-safe SQLite database connection manager."""

    def __init__(self, db_name: str = "words.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self._lock = Lock()
        
        # Optimize SQLite settings
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")

    @contextmanager
    def _cursor(self, commit: bool = False):
        """Context manager for database cursors with proper error handling."""
        with self._lock:
            cur = self.conn.cursor()
            try:
                yield cur
                if commit:
                    self.conn.commit()
            except sqlite3.Error as e:
                self.conn.rollback()
                logger.error("Database error: %s", e)
                raise
            finally:
                cur.close()

    def close(self):
        """Close the database connection."""
        with self._lock:
            if self.conn:
                self.conn.close()
                logger.info("Database connection closed")

    def backup(self, backup_path: Optional[str] = None) -> str:
        """Create a backup of the database."""
        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{self.db_name}.backup_{timestamp}"
        
        with self._lock:
            try:
                backup_conn = sqlite3.connect(backup_path)
                self.conn.backup(backup_conn)
                backup_conn.close()
                logger.info("Database backup created: %s", backup_path)
                return backup_path
            except sqlite3.Error as e:
                logger.error("Backup failed: %s", e)
                raise
