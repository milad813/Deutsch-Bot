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
            "accuracy": (
                int((total_correct / total_answers) * 100) if total_answers else 0
            ),
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
        streak: int = 0,
    ) -> None:
        """Record grammar exercise answer with adaptive intervals."""
        now = datetime.now(timezone.utc)

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
            last_reviewed, next_review
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
        """تعداد کلمات یکتای تمرین‌شده امروز (نه مجموع تعاملات)."""
        from datetime import datetime, timedelta, timezone
        from config import USER_TIMEZONE_OFFSET_HOURS, USER_TIMEZONE_OFFSET_MINUTES

        tz = timezone(
            timedelta(
                hours=USER_TIMEZONE_OFFSET_HOURS,
                minutes=USER_TIMEZONE_OFFSET_MINUTES,
            )
        )
        now_local = datetime.now(tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_local.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        row = self.fetch_one(
            """
            SELECT COUNT(DISTINCT word_id)
            FROM word_stats
            WHERE user_id = ? AND last_reviewed >= ?
            """,
            (user_id, today_start_utc),
        )
        return row[0] if row and row[0] else 0

    def get_total_learned_words_count(self, user_id: int) -> int:
        """تعداد کل کلماتی که کاربر حداقل یک‌بار تعامل داشته."""
        row = self.fetch_one(
            "SELECT COUNT(*) FROM word_stats WHERE user_id = ?",
            (user_id,),
        )
        return row[0] if row and row[0] else 0

    def get_today_new_words_count(self, user_id: int) -> int:
        """تعداد کلماتی که امروز برای اولین بار دیده شده‌اند."""
        from datetime import datetime, timedelta, timezone
        from config import USER_TIMEZONE_OFFSET_HOURS, USER_TIMEZONE_OFFSET_MINUTES

        tz = timezone(
            timedelta(
                hours=USER_TIMEZONE_OFFSET_HOURS,
                minutes=USER_TIMEZONE_OFFSET_MINUTES,
            )
        )
        now_local = datetime.now(tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_local.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        row = self.fetch_one(
            """
            SELECT COUNT(DISTINCT word_id)
            FROM word_skills
            WHERE user_id = ? AND last_reviewed >= ?
            AND word_id NOT IN (
                SELECT DISTINCT word_id FROM word_skills
                WHERE user_id = ? AND last_reviewed < ?
            )
            """,
            (user_id, today_start_utc, user_id, today_start_utc),
        )
        return row[0] if row and row[0] else 0

    def get_weekly_stats(self, user_id: int) -> Dict:
        """آمار ۷ روز اخیر با روزهای فعال بر اساس وقت محلی کاربر."""
        from config import USER_TIMEZONE_OFFSET_HOURS, USER_TIMEZONE_OFFSET_MINUTES

        tz = timezone(
            timedelta(
                hours=USER_TIMEZONE_OFFSET_HOURS,
                minutes=USER_TIMEZONE_OFFSET_MINUTES,
            )
        )

        now_local = datetime.now(tz)

        start_local = (now_local - timedelta(days=6)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        start_utc = start_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        rows = self.fetch_all(
            """
            SELECT last_reviewed, correct_count, wrong_count
            FROM word_skills
            WHERE user_id = ? AND last_reviewed >= ?
            """,
            (user_id, start_utc),
        )

        correct_total = 0
        wrong_total = 0
        active_days = set()

        for last_reviewed, correct_count, wrong_count in rows:
            correct_total += correct_count or 0
            wrong_total += wrong_count or 0

            if not last_reviewed:
                continue

            value = str(last_reviewed).strip()
            dt = None

            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
            ):
                try:
                    dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
                    break
                except Exception:
                    pass

            if dt is None:
                try:
                    dt = datetime.fromisoformat(value.replace("Z", ""))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt = dt.astimezone(timezone.utc)
                except Exception:
                    dt = None

            if dt:
                local_dt = dt.astimezone(tz)
                active_days.add(local_dt.date())

        total = correct_total + wrong_total

        return {
            "total_answers": total,
            "correct": correct_total,
            "wrong": wrong_total,
            "accuracy": int(correct_total / total * 100) if total else 0,
            "active_days": len(active_days),
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

    # ─────────────────────────────
    # Daily LLM usage quota
    # ─────────────────────────────
    def _today_local_str(self) -> str:
        """Return today's date in the configured user-local timezone as
        ``YYYY-MM-DD``. Used as the partition key for ``user_llm_usage`` so
        that daily quotas naturally roll over at local midnight without
        needing a cron job.
        """
        from config import (
            USER_TIMEZONE_OFFSET_HOURS,
            USER_TIMEZONE_OFFSET_MINUTES,
        )

        tz = timezone(
            timedelta(
                hours=USER_TIMEZONE_OFFSET_HOURS,
                minutes=USER_TIMEZONE_OFFSET_MINUTES,
            )
        )
        return datetime.now(tz).strftime("%Y-%m-%d")

    def get_llm_usage(
        self, user_id: int, usage_date: Optional[str] = None
    ) -> Dict:
        """Return the user's LLM usage counters for ``usage_date`` (defaults
        to today in the configured user-local timezone).

        The returned dict always has ``"story"`` and ``"example"`` keys; a
        user with no row for that date is treated as a fresh user with
        both counts at zero.
        """
        if usage_date is None:
            usage_date = self._today_local_str()

        row = self.fetch_one(
            """
            SELECT story_count, example_count
            FROM user_llm_usage
            WHERE user_id = ? AND usage_date = ?
            """,
            (user_id, usage_date),
        )

        if not row:
            return {"story": 0, "example": 0}

        return {
            "story": int(row[0] or 0),
            "example": int(row[1] or 0),
        }

    def increment_llm_usage(
        self,
        user_id: int,
        feature: str,
        usage_date: Optional[str] = None,
    ) -> None:
        """Atomically increment the counter for ``feature`` (``"story"`` or
        ``"example"``) on the user's row for ``usage_date`` (default: today).

        Uses an UPSERT so the first call for a given (user, date) inserts a
        fresh row, and subsequent calls add 1 to the chosen counter. The
        other counter is preserved. Unknown ``feature`` values are silently
        ignored so a typo cannot corrupt the table.
        """
        if feature not in ("story", "example"):
            return

        if usage_date is None:
            usage_date = self._today_local_str()

        # The CASE expression picks the right column to bump; the other
        # one is set to its current value so the INSERT and UPDATE paths
        # both produce a row with consistent columns.
        if feature == "story":
            self.execute(
                """
                INSERT INTO user_llm_usage (
                    user_id, usage_date, story_count, example_count, last_updated
                )
                VALUES (?, ?, 1, 0, ?)
                ON CONFLICT(user_id, usage_date) DO UPDATE SET
                    story_count = user_llm_usage.story_count + 1,
                    last_updated = excluded.last_updated
                """,
                (user_id, usage_date, _now_str()),
                commit=True,
            )
        else:  # feature == "example"
            self.execute(
                """
                INSERT INTO user_llm_usage (
                    user_id, usage_date, story_count, example_count, last_updated
                )
                VALUES (?, ?, 0, 1, ?)
                ON CONFLICT(user_id, usage_date) DO UPDATE SET
                    example_count = user_llm_usage.example_count + 1,
                    last_updated = excluded.last_updated
                """,
                (user_id, usage_date, _now_str()),
                commit=True,
            )

    def is_llm_action_allowed(self, user_id: int, feature: str) -> bool:
        """Return whether the user is still under their daily quota for the
        given ``feature`` (``"story"`` or ``"example"``).

        The check is based on the current counter in ``user_llm_usage`` for
        today (in the configured user-local timezone). Comparing against
        ``<`` (not ``<=``) means a user can make exactly ``limit`` calls
        per day, not ``limit - 1``.

        Unknown features and configuration errors fail closed (return
        ``False``) so a misconfigured deploy never silently grants more
        LLM calls than intended.
        """
        import config

        if feature == "story":
            limit = getattr(config, "LLM_DAILY_STORY_LIMIT", 0)
        elif feature == "example":
            limit = getattr(config, "LLM_DAILY_EXAMPLE_LIMIT", 0)
        else:
            return False

        # limit <= 0 is treated as "feature disabled" — refuse rather than
        # silently allowing an infinite number of calls.
        if not isinstance(limit, int) or limit <= 0:
            return False

        usage = self.get_llm_usage(user_id)
        return usage.get(feature, 0) < limit

    def get_llm_usage_totals_today(self) -> Dict[str, int]:
        """Return ``{"story": N, "example": M}`` totals across **all** users
        for today's local date.

        Used by the admin ``/status`` view to surface a quick at-a-glance
        "how many LLM calls have been made today" number. Sums
        ``story_count`` and ``example_count`` over every row of
        ``user_llm_usage`` whose ``usage_date`` matches
        :meth:`_today_local_str`.

        Robustness contract:

        * **Empty table / empty matching set** → returns
          ``{"story": 0, "example": 0}`` (no rows is a legitimate state
          for a fresh deploy or a day nobody has pinged the LLM).
        * **Table missing** (e.g. running against a pre-Phase-1
          database that predates the schema) → also returns
          ``{"story": 0, "example": 0}`` instead of bubbling up a
          ``sqlite3.OperationalError`` that would brick ``/status``.
        * **Other DB errors** → return zeros, *not* raise, so a transient
          I/O blip never makes the admin page render as broken.
        """
        import sqlite3

        try:
            row = self.fetch_one(
                """
                SELECT COALESCE(SUM(story_count), 0),
                       COALESCE(SUM(example_count), 0)
                FROM user_llm_usage
                WHERE usage_date = ?
                """,
                (self._today_local_str(),),
            )
        except sqlite3.OperationalError:
            # ``user_llm_usage`` doesn't exist on this DB. Treat as "no
            # usage recorded" rather than a hard failure for the admin
            # status view.
            return {"story": 0, "example": 0}
        except Exception:
            return {"story": 0, "example": 0}

        if not row:
            return {"story": 0, "example": 0}

        return {
            "story": int(row[0] or 0),
            "example": int(row[1] or 0),
        }
