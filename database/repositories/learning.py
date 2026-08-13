"""Repository for unified learning progress."""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from database.repositories.base import BaseRepository


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class LearningRepository(BaseRepository):
    """Unified progress repository for skills, mistakes, grammar, story and LLM examples."""

    # ─────────────────────────────
    # Word skills
    # ─────────────────────────────
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
    def get_word_mastery(self, user_id: int, word_id: int) -> Optional[Dict]:
        """Get simple overall mastery for a word."""
        skills = self.get_word_skills(user_id, word_id)
        if not skills:
            return None

        total_correct = sum(s["correct"] for s in skills)
        total_answers = sum(s["total"] for s in skills)

        return {
            "word_id": word_id,
            "skills": skills,
            "total_correct": total_correct,
            "total_answers": total_answers,
            "accuracy": int((total_correct / total_answers) * 100)
            if total_answers
            else 0,
        }

    # ─────────────────────────────
    # Mistakes
    # ─────────────────────────────
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

    # ─────────────────────────────
    # Grammar progress
    # ─────────────────────────────
    def record_grammar_answer(
        self,
        user_id: int,
        grammar_point_id: int,
        is_correct: bool,
    ) -> None:
        """Record grammar exercise answer."""
        now = datetime.now(timezone.utc)

        # فعلاً ساده نگه می‌داریم:
        # اگر غلط بود، ۴ ساعت بعد دوباره مرور شود.
        # اگر درست بود، ۱ روز بعد.
        if is_correct:
            next_review = now + timedelta(days=1)
        else:
            next_review = now + timedelta(hours=4)

        query = """
        INSERT INTO grammar_progress (
            user_id,
            grammar_point_id,
            correct_count,
            wrong_count,
            last_reviewed,
            next_review
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, grammar_point_id) DO UPDATE SET
            correct_count = correct_count + excluded.correct_count,
            wrong_count = wrong_count + excluded.wrong_count,
            last_reviewed = excluded.last_reviewed,
            next_review = excluded.next_review
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
            ),
            commit=True,
        )

    def get_grammar_progress(self, user_id: int, grammar_point_id: int) -> Dict:
        """Get progress for one grammar point."""
        row = self.fetch_one(
            """
            SELECT correct_count, wrong_count, next_review
            FROM grammar_progress
            WHERE user_id = ? AND grammar_point_id = ?
            """,
            (user_id, grammar_point_id),
        )

        if not row:
            return {
                "correct": 0,
                "wrong": 0,
                "total": 0,
                "accuracy": 0,
                "next_review": None,
            }

        correct = row[0] or 0
        wrong = row[1] or 0
        total = correct + wrong

        return {
            "correct": correct,
            "wrong": wrong,
            "total": total,
            "accuracy": int((correct / total) * 100) if total else 0,
            "next_review": row[2],
        }

    # ─────────────────────────────
    # Story progress
    # ─────────────────────────────
    def record_story_answer(
        self,
        user_id: int,
        story_id: int,
        is_correct: bool,
    ) -> None:
        """Record story comprehension answer."""
        query = """
        INSERT INTO story_progress (
            user_id,
            story_id,
            correct_count,
            wrong_count,
            last_reviewed
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, story_id) DO UPDATE SET
            correct_count = correct_count + excluded.correct_count,
            wrong_count = wrong_count + excluded.wrong_count,
            last_reviewed = excluded.last_reviewed
        """

        self.execute(
            query,
            (
                user_id,
                story_id,
                1 if is_correct else 0,
                0 if is_correct else 1,
                _now_str(),
            ),
            commit=True,
        )

    def get_story_progress(self, user_id: int, story_id: int) -> Dict:
        """Get progress for one story."""
        row = self.fetch_one(
            """
            SELECT correct_count, wrong_count, last_reviewed
            FROM story_progress
            WHERE user_id = ? AND story_id = ?
            """,
            (user_id, story_id),
        )

        if not row:
            return {
                "correct": 0,
                "wrong": 0,
                "total": 0,
                "accuracy": 0,
                "last_reviewed": None,
            }

        correct = row[0] or 0
        wrong = row[1] or 0
        total = correct + wrong

        return {
            "correct": correct,
            "wrong": wrong,
            "total": total,
            "accuracy": int((correct / total) * 100) if total else 0,
            "last_reviewed": row[2],
        }

    # ─────────────────────────────
    # LLM example cache
    # ─────────────────────────────
    def get_llm_example(self, word_id: int, level: str) -> Optional[Dict]:
        """Get cached LLM example for a word."""
        row = self.fetch_one(
            """
            SELECT example_de, example_fa
            FROM llm_examples
            WHERE word_id = ? AND level = ?
            """,
            (word_id, level),
        )

        if not row or not row[0]:
            return None

        return {
            "de": row[0],
            "fa": row[1],
        }

    def save_llm_example(
        self,
        word_id: int,
        level: str,
        example_de: str,
        example_fa: Optional[str] = None,
    ) -> None:
        """Save/cache generated LLM example."""
        if not word_id or not example_de:
            return

        self.execute(
            """
            INSERT INTO llm_examples (
                word_id,
                level,
                example_de,
                example_fa
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(word_id, level) DO UPDATE SET
                example_de = excluded.example_de,
                example_fa = excluded.example_fa,
                created_at = CURRENT_TIMESTAMP
            """,
            (word_id, level, example_de, example_fa),
            commit=True,
        )

    # ─────────────────────────────
    # Daily goal
    # ─────────────────────────────
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
        """تعداد فعالیت‌های امروز به وقت محلی کاربر."""
        from config import USER_TIMEZONE_OFFSET_HOURS, USER_TIMEZONE_OFFSET_MINUTES
        from datetime import datetime, timedelta, timezone

        tz = timezone(
            timedelta(
                hours=USER_TIMEZONE_OFFSET_HOURS,
                minutes=USER_TIMEZONE_OFFSET_MINUTES,
            )
        )

        now_local = datetime.now(tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

        # ✅ تبدیل درست به UTC
        today_start_utc = today_start_local.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        row = self.fetch_one(
            """
            SELECT SUM(correct_count + wrong_count)
            FROM word_skills
            WHERE user_id = ? AND last_reviewed >= ?
            """,
            (user_id, today_start_utc),
        )

        return row[0] if row and row[0] else 0
    def get_weekly_stats(self, user_id: int) -> Dict:
        """آمار ۷ روز اخیر."""
        row = self.fetch_one(
            """
            SELECT 
                SUM(correct_count) as correct,
                SUM(wrong_count) as wrong,
                COUNT(DISTINCT date(last_reviewed)) as active_days
            FROM word_skills
            WHERE user_id = ? AND last_reviewed >= datetime('now', '-7 days')
            """,
            (user_id,),
        )
        if not row:
            return {"total_answers": 0, "correct": 0, "wrong": 0, "accuracy": 0, "active_days": 0}
        correct = row[0] or 0
        wrong = row[1] or 0
        total = correct + wrong
        return {
            "total_answers": total,
            "correct": correct,
            "wrong": wrong,
            "accuracy": int(correct / total * 100) if total else 0,
            "active_days": row[2] or 0,
        }

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
