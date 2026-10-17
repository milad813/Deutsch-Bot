"""Practice persistence."""

from datetime import datetime, timedelta, timezone
from database.repositories.base import BaseRepository

from database.time_utils import utc_now_string as _now_str


class PracticeProgressRepository(BaseRepository):
    def record_grammar_answer(
        self,
        user_id: int,
        grammar_point_id: int,
        is_correct: bool,
    ) -> None:
        """Record grammar exercise answer with adaptive intervals."""
        with self._conn.transaction():
            now = datetime.now(timezone.utc)

            previous = self.fetch_one(
                "SELECT correct_streak FROM grammar_progress "
                "WHERE user_id = ? AND grammar_point_id = ?",
                (user_id, grammar_point_id),
            )
            streak = int(previous[0] or 0) if previous else 0
            if is_correct:
                streak += 1
                # فاصله‌های تطبیقی بر اساس streak
                intervals_days = {1: 1, 2: 2, 3: 4, 4: 7, 5: 14}
                days = intervals_days.get(min(streak, 5), 21)
                next_review = now + timedelta(days=days)
            else:
                streak = 0
                next_review = now + timedelta(hours=4)

            query = """
            INSERT INTO grammar_progress (
                user_id, grammar_point_id, correct_count, wrong_count,
                last_reviewed, next_review, correct_streak
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, grammar_point_id) DO UPDATE SET
                correct_count = correct_count + excluded.correct_count,
                wrong_count = wrong_count + excluded.wrong_count,
                last_reviewed = excluded.last_reviewed,
                next_review = excluded.next_review,
                correct_streak = excluded.correct_streak
            """
            self.execute(
                query,
                (
                    user_id,
                    grammar_point_id,
                    1 if is_correct else 0,
                    0 if is_correct else 1,
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    next_review.strftime("%Y-%m-%d %H:%M:%S"),
                    streak,
                ),
                commit=True,
            )

    def record_story_answer(self, user_id: int, story_id: int, is_correct: bool) -> None:
        """Record story comprehension answer with next review scheduling."""
        now = datetime.now(timezone.utc)

        if is_correct:
            next_review = now + timedelta(days=3)
        else:
            next_review = now + timedelta(hours=12)

        query = """
        INSERT INTO story_progress (
            user_id, story_id, correct_count, wrong_count, last_reviewed, next_review
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, story_id) DO UPDATE SET
            correct_count = correct_count + excluded.correct_count,
            wrong_count = wrong_count + excluded.wrong_count,
            last_reviewed = excluded.last_reviewed,
            next_review = excluded.next_review
        """
        self.execute(
            query,
            (
                user_id,
                story_id,
                1 if is_correct else 0,
                0 if is_correct else 1,
                _now_str(),
                next_review.strftime("%Y-%m-%d %H:%M:%S"),
            ),
            commit=True,
        )
