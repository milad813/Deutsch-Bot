"""Repository pattern for user-related database operations."""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class UserRepository:
    """Repository for user-related database operations."""

    def __init__(self, db_connection):
        self.db = db_connection

    def get_or_create_stats(self, user_id: int) -> Dict:
        """Get or create user statistics."""
        with self.db._cursor() as c:
            c.execute("SELECT correct_answers, total_answers FROM user_stats WHERE user_id = ?", (user_id,))
            row = c.fetchone()
            
            if not row:
                c.execute(
                    "INSERT INTO user_stats (user_id) VALUES (?)",
                    (user_id,),
                )
                self.db.conn.commit()
                return {"correct": 0, "total": 0}
            
            return {"correct": row[0], "total": row[1]}

    def update_stats(self, user_id: int, correct: bool) -> None:
        """Update user quiz statistics."""
        with self.db._cursor(commit=True) as c:
            c.execute(
                """
                INSERT INTO user_stats (user_id, correct_answers, total_answers)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                correct_answers = correct_answers + ?,
                total_answers = total_answers + 1
                """,
                (user_id, 1 if correct else 0, 1, 1 if correct else 0, 1),
            )

    def get_progress(self, user_id: int) -> Dict:
        """Get user progress (XP, streak, etc.)."""
        with self.db._cursor() as c:
            c.execute(
                "SELECT xp, streak, last_active_date FROM user_progress WHERE user_id = ?",
                (user_id,),
            )
            row = c.fetchone()
            
            if not row:
                return {"xp": 0, "streak": 0, "last_active": None}
            
            return {
                "xp": row[0],
                "streak": row[1],
                "last_active": row[2],
            }

    def update_progress(self, user_id: int, xp_delta: int = 0) -> Dict:
        """Update user progress and return updated values."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        with self.db._cursor(commit=True) as c:
            # Get current progress
            c.execute(
                "SELECT xp, streak, last_active_date FROM user_progress WHERE user_id = ?",
                (user_id,),
            )
            row = c.fetchone()
            
            if row:
                current_xp, streak, last_active = row
                
                # Calculate new streak
                if last_active == today:
                    new_streak = streak
                elif last_active and (datetime.strptime(today, "%Y-%m-%d") - 
                                      datetime.strptime(last_active, "%Y-%m-%d")).days == 1:
                    new_streak = streak + 1
                else:
                    new_streak = 1
                
                new_xp = current_xp + xp_delta
                
                c.execute(
                    """
                    UPDATE user_progress
                    SET xp = ?, streak = ?, last_active_date = ?
                    WHERE user_id = ?
                    """,
                    (new_xp, new_streak, today, user_id),
                )
            else:
                new_xp = xp_delta
                new_streak = 1
                c.execute(
                    """
                    INSERT INTO user_progress (user_id, xp, streak, last_active_date)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, new_xp, new_streak, today),
                )
            
            return {"xp": new_xp, "streak": new_streak, "last_active": today}

    def get_settings(self, user_id: int) -> Dict:
        """Get user settings."""
        with self.db._cursor() as c:
            c.execute(
                "SELECT preferred_level FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            row = c.fetchone()
            
            if not row:
                return {"preferred_level": "A1"}
            
            return {"preferred_level": row[0]}

    def update_settings(self, user_id: int, preferred_level: str) -> None:
        """Update user settings."""
        with self.db._cursor(commit=True) as c:
            c.execute(
                """
                INSERT INTO user_settings (user_id, preferred_level)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                preferred_level = ?
                """,
                (user_id, preferred_level, preferred_level),
            )
