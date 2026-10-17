"""Ltr persistence."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from database.repositories.base import BaseRepository

from database.time_utils import utc_now_string as _now_str


class LTRRepository(BaseRepository):
    def observe_ltr_word(self, user_id: int, word_id: int) -> None:
        """Persist an observation without inventing a correct or wrong answer."""
        with self._conn.transaction():
            self.execute(
                "INSERT OR IGNORE INTO word_first_seen VALUES (?, ?, ?)",
                (user_id, word_id, _now_str()),
                commit=True,
            )
            self.defer_ltr_review(user_id, word_id)

    def get_ltr_finalization(self, session_id: str, user_id: int, word_id: int) -> Optional[str]:
        row = self.fetch_one(
            "SELECT next_review FROM ltr_finalizations WHERE session_id=? AND user_id=? AND word_id=?",
            (session_id, user_id, word_id),
        )
        return str(row[0]) if row else None

    def save_ltr_finalization(self, session_id: str, user_id: int, word_id: int, next_review: str):
        self.execute(
            "INSERT INTO ltr_finalizations VALUES (?,?,?,?)",
            (session_id, user_id, word_id, next_review),
            commit=True,
        )

    def defer_ltr_review(self, user_id: int, word_id: int) -> str:
        """Schedule unfinished learning soon, preserving an earlier existing due time."""
        due = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        self.execute(
            """INSERT INTO word_stats (user_id, word_id, next_review, phase)
               VALUES (?, ?, ?, 'learning')
               ON CONFLICT(user_id, word_id) DO UPDATE SET
                   next_review = CASE
                       WHEN word_stats.next_review IS NULL OR word_stats.next_review > excluded.next_review
                       THEN excluded.next_review ELSE word_stats.next_review END,
                   phase = 'learning'""",
            (user_id, word_id, due),
            commit=True,
        )
        row = self.fetch_one(
            "SELECT next_review FROM word_stats WHERE user_id = ? AND word_id = ?",
            (user_id, word_id),
        )
        if row is None:
            raise RuntimeError("LTR review was not saved")
        return str(row[0])

    def record_ltr_attempt(
        self,
        user_id,
        word_id,
        attempt_id,
        question_type,
        is_correct,
        assisted,
        user_answer,
        correct_answer,
    ) -> bool:
        with self.cursor(commit=True) as cursor:
            cursor.execute(
                """INSERT OR IGNORE INTO ltr_attempts
                   (attempt_id,user_id,word_id,question_type,is_correct,assisted,
                    user_answer,correct_answer,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    attempt_id,
                    user_id,
                    word_id,
                    question_type,
                    int(is_correct),
                    int(assisted),
                    user_answer,
                    correct_answer,
                    _now_str(),
                ),
            )
            return cursor.rowcount == 1

    def get_ltr_success_types(self, user_id: int, word_id: int) -> List[str]:
        """Carry valid practice across sessions; guidance never grants independent credit."""
        return [
            row[0]
            for row in self.fetch_all(
                """SELECT DISTINCT question_type FROM ltr_attempts
               WHERE user_id=? AND word_id=? AND is_correct=1 AND assisted=0
               AND rowid > COALESCE((SELECT MAX(rowid) FROM ltr_attempts
                   WHERE user_id=? AND word_id=? AND is_correct=0), 0)""",
                (user_id, word_id, user_id, word_id),
            )
        ]
