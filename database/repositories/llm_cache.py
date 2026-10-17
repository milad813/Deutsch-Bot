"""Llm Cache persistence."""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import sqlite3
from database.repositories.base import BaseRepository

from database.time_utils import utc_now_string as _now_str


class LLMRepository(BaseRepository):
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

    def get_llm_usage(self, user_id: int, usage_date: Optional[str] = None) -> Dict:
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
