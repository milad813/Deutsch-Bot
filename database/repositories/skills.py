"""Skills persistence."""

from typing import Dict, List, Optional
from database.repositories.base import BaseRepository

from database.time_utils import utc_now_string as _now_str


class WordSkillRepository(BaseRepository):
    def record_skill(
        self,
        user_id: int,
        word_id: int,
        skill_type: str,
        is_correct: bool,
    ) -> None:
        """Record one skill attempt for a word."""
        if not word_id:
            return

        now_str = _now_str()
        self.execute(
            "INSERT OR IGNORE INTO word_first_seen VALUES (?, ?, ?)",
            (user_id, word_id, now_str),
            commit=True,
        )
        wrong_at = now_str if not is_correct else None

        correct_inc = 1 if is_correct else 0
        wrong_inc = 0 if is_correct else 1
        streak_value = 1 if is_correct else 0

        query = """
        INSERT INTO word_skills (
            user_id,
            word_id,
            skill_type,
            correct_count,
            wrong_count,
            last_reviewed,
            last_wrong_at,
            correct_streak
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, word_id, skill_type) DO UPDATE SET
            correct_count = word_skills.correct_count + excluded.correct_count,
            wrong_count = word_skills.wrong_count + excluded.wrong_count,
            last_reviewed = excluded.last_reviewed,
            last_wrong_at = CASE
                WHEN excluded.wrong_count > 0 THEN excluded.last_wrong_at
                ELSE word_skills.last_wrong_at
            END,
            correct_streak = CASE
                WHEN excluded.correct_count > 0 THEN COALESCE(word_skills.correct_streak, 0) + 1
                ELSE 0
            END
        """

        self.execute(
            query,
            (
                user_id,
                word_id,
                skill_type,
                correct_inc,
                wrong_inc,
                now_str,
                wrong_at,
                streak_value,
            ),
            commit=True,
        )

        # ✅ اگر کاربر در همان skill درست زد، اشتباه همان skill حل شود
        if is_correct:
            self.execute(
                """
                UPDATE mistake_stats
                SET resolved_at = ?
                WHERE user_id = ?
                  AND word_id = ?
                  AND skill_type = ?
                  AND resolved_at IS NULL
                """,
                (now_str, user_id, word_id, skill_type),
                commit=True,
            )

    def get_word_skills(self, user_id: int, word_id: int) -> List[Dict]:
        """Get all skill stats for one word."""
        rows = self.fetch_all(
            """
            SELECT skill_type, correct_count, wrong_count, correct_streak
            FROM word_skills
            WHERE user_id = ? AND word_id = ?
            ORDER BY skill_type
            """,
            (user_id, word_id),
        )

        result = []
        for skill_type, correct, wrong, streak in rows:
            correct = correct or 0
            wrong = wrong or 0
            streak = streak or 0
            total = correct + wrong

            result.append(
                {
                    "skill_type": skill_type,
                    "correct": correct,
                    "wrong": wrong,
                    "total": total,
                    "accuracy": int((correct / total) * 100) if total else 0,
                    "correct_streak": streak,
                }
            )

        return result

    def record_mistake(
        self,
        user_id: int,
        word_id: Optional[int] = None,
        grammar_point_id: Optional[int] = None,
        story_id: Optional[int] = None,
        skill_type: Optional[str] = None,
        quiz_type: Optional[str] = None,
        user_answer: Optional[str] = None,
        correct_answer: Optional[str] = None,
    ) -> None:
        """Record a mistake and update mistake stats if it is about a word."""
        skill_type = skill_type or quiz_type or "general"

        self.execute(
            """
            INSERT INTO mistakes (
                user_id,
                word_id,
                grammar_point_id,
                story_id,
                skill_type,
                quiz_type,
                user_answer,
                correct_answer
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                word_id,
                grammar_point_id,
                story_id,
                skill_type,
                quiz_type,
                user_answer,
                correct_answer,
            ),
            commit=True,
        )

        if word_id:
            self.execute(
                """
                INSERT INTO mistake_stats (
                    user_id,
                    word_id,
                    skill_type,
                    wrong_count,
                    last_wrong_at
                )
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(user_id, word_id, skill_type) DO UPDATE SET
                    wrong_count = wrong_count + 1,
                    last_wrong_at = excluded.last_wrong_at,
                    resolved_at = NULL
                """,
                (user_id, word_id, skill_type, _now_str()),
                commit=True,
            )

    def get_mistake_words(self, user_id: int, limit: int = 20) -> List[Dict]:
        """Get words with unresolved mistakes."""
        rows = self.fetch_all(
            """
            SELECT
                ms.word_id,
                w.german,
                w.persian,
                w.article,
                SUM(ms.wrong_count) AS wrong_count,
                MAX(ms.last_wrong_at) AS last_wrong_at
            FROM mistake_stats ms
            JOIN words w ON w.id = ms.word_id
            WHERE ms.user_id = ? AND ms.resolved_at IS NULL
            GROUP BY ms.word_id
            ORDER BY wrong_count DESC, last_wrong_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )

        return [
            {
                "word_id": r[0],
                "german": r[1],
                "persian": r[2],
                "article": r[3],
                "wrong_count": r[4],
                "last_wrong_at": r[5],
            }
            for r in rows
        ]

    def get_mistake_word_count(self, user_id: int) -> int:
        """تعداد کلمات با اشتباه حل‌نشده."""
        row = self.fetch_one(
            """
            SELECT COUNT(DISTINCT word_id)
            FROM mistake_stats
            WHERE user_id = ? AND resolved_at IS NULL AND wrong_count > 0
            """,
            (user_id,),
        )
        return row[0] if row else 0
