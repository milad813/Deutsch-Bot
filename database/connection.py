"""Database connection management and migrations."""

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_OWNER_ID = 1


def _utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class DatabaseConnection:
    """Manages SQLite database connection."""

    def __init__(self, db_name: str = "words.db"):
        self.db_name = db_name
        self._write_lock = threading.Lock()
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self._setup_connection()

    def _setup_connection(self) -> None:
        """Configure SQLite connection with optimal settings."""
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")

    @contextmanager
    def cursor(self, commit: bool = False):
        if commit:
            self._write_lock.acquire()
        try:
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
        finally:
            if commit:
                self._write_lock.release()

    def close(self) -> None:
        """Close database connection."""
        try:
            self.conn.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error("Error closing database: %s", e)

    def _cleanup_old_backups(
        self, backup_dir: str, keep_days: int = 14, keep_max: int = 30
    ):
        try:
            from config import BACKUP_KEEP_DAYS, BACKUP_KEEP_MAX

            keep_days = BACKUP_KEEP_DAYS
            keep_max = BACKUP_KEEP_MAX
        except Exception:
            pass
        try:
            if not os.path.isdir(backup_dir):
                return
            files = []
            for name in os.listdir(backup_dir):
                if name.startswith("words_") and name.endswith(".db"):
                    path = os.path.join(backup_dir, name)
                    if os.path.isfile(path):
                        files.append((path, os.path.getmtime(path)))
            files.sort(key=lambda item: item[1], reverse=True)
            now = time.time()
            for index, (path, mtime) in enumerate(files):
                too_old = (now - mtime) > (keep_days * 86400)
                if index >= keep_max or too_old:
                    try:
                        os.unlink(path)
                        logger.info("بکاپ قدیمی حذف شد: %s", path)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("خطا در پاک‌سازی بکاپ‌ها: %s", e)

    def backup(self, backup_dir: str = "backups") -> str:
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"words_{timestamp}.db")
        dest = sqlite3.connect(backup_path)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
        self._cleanup_old_backups(backup_dir)
        return backup_path
