"""Learning Stats persistence."""

from database.repositories.base import BaseRepository


class LearningStatsRepository(BaseRepository):
    def set_daily_goal(self, user_id: int, goal: int) -> None:
        """تنظیم هدف روزانه (تعداد کلمه)."""
        self.execute(
            """
            INSERT INTO user_settings (user_id, preferred_level, daily_goal)
            VALUES (?, 'A1', ?)
            ON CONFLICT(user_id) DO UPDATE SET daily_goal = excluded.daily_goal
            """,
            (user_id, goal),
            commit=True,
        )

    def get_daily_goal(self, user_id: int) -> int:
        row = self.fetch_one(
            "SELECT daily_goal FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        return row[0] if row and row[0] else 10

    def get_today_activity_count(self, user_id: int) -> int:
        """Count distinct reviewed words in the user's local day."""
        start, end = self.day_bounds(user_id)
        row = self.fetch_one(
            "SELECT COUNT(DISTINCT word_id) FROM word_stats "
            "WHERE user_id=? AND last_reviewed >= ? AND last_reviewed < ?",
            (user_id, start, end),
        )
        return int(row[0]) if row else 0

    def get_total_learned_words_count(self, user_id: int) -> int:
        """تعداد کل کلماتی که کاربر حداقل یک‌بار تعامل داشته."""
        row = self.fetch_one(
            "SELECT COUNT(*) FROM word_stats WHERE user_id = ?",
            (user_id,),
        )
        return row[0] if row and row[0] else 0

    def get_today_new_words_count(self, user_id: int) -> int:
        """Count first observations, never recent reviews of older words."""
        start, end = self.day_bounds(user_id)
        row = self.fetch_one(
            "SELECT COUNT(*) FROM word_first_seen "
            "WHERE user_id=? AND first_seen_at >= ? AND first_seen_at < ?",
            (user_id, start, end),
        )
        return int(row[0]) if row else 0
