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

    def __init__(
        self,
        db_name: str = "words.db",
        backup_keep_days: int = 14,
        backup_keep_max: int = 30,
    ):
        self.db_name = db_name
        self._op_lock = threading.RLock()
        self._transaction_depth = 0
        # Backup retention is injected (wired from config by the container),
        # keeping this module free of config imports.
        self.backup_keep_days = backup_keep_days
        self.backup_keep_max = backup_keep_max
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        try:
            self._setup_connection()
        except BaseException:
            self.conn.close()
            raise

    def _setup_connection(self) -> None:
        """Configure SQLite connection with optimal settings."""
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")

    @contextmanager
    def cursor(self, commit: bool = False):
        with self._op_lock:
            cur = self.conn.cursor()
            try:
                yield cur
                if commit and not self._transaction_depth:
                    self.conn.commit()
            except BaseException:
                if not self._transaction_depth:
                    self.conn.rollback()
                raise
            finally:
                cur.close()

    @contextmanager
    def transaction(self):
        """Hold the connection lock and defer commits for one unit of work."""
        with self._op_lock:
            name = f"learning_{self._transaction_depth}"
            self.conn.execute(f"SAVEPOINT {name}")
            self._transaction_depth += 1
            try:
                yield
            except BaseException:
                self.conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
                self.conn.execute(f"RELEASE SAVEPOINT {name}")
                raise
            else:
                self.conn.execute(f"RELEASE SAVEPOINT {name}")
            finally:
                self._transaction_depth -= 1

    def close(self) -> None:
        """Close database connection."""
        try:
            with self._op_lock:
                self.conn.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error("Error closing database: %s", e)

    def _cleanup_old_backups(self, backup_dir: str):
        keep_days = self.backup_keep_days
        keep_max = self.backup_keep_max
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
        timestamp = _utc_now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = os.path.join(backup_dir, f"words_{timestamp}.db")
        dest = sqlite3.connect(backup_path)
        try:
            with self._op_lock:
                self.conn.backup(dest)
        finally:
            dest.close()
        self._cleanup_old_backups(backup_dir)
        return backup_path
