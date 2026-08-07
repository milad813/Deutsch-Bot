"""Repository pattern for word-related database operations."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Iterable

from app.models import Word

logger = logging.getLogger(__name__)


class WordRepository:
    """Repository for word-related database operations."""

    def __init__(self, db_connection):
        self.db = db_connection

    def _word_columns(self, alias: Optional[str] = None) -> str:
        prefix = f"{alias}." if alias else ""
        return (
            f"{prefix}id, {prefix}german, {prefix}persian, {prefix}article, "
            f"{prefix}word_type, {prefix}example_de, {prefix}example_fa, {prefix}english_meaning, "
            f"{prefix}plural_form, {prefix}verb_forms, {prefix}comparative, "
            f"{prefix}collocation_de, {prefix}collocation_fa"
        )

    def _row_to_word(self, row: Tuple) -> Word:
        """Convert a database row to a Word object."""
        return Word(
            id=row[0],
            german=row[1],
            persian=row[2],
            article=row[3],
            word_type=row[4],
            example_de=row[5],
            example_fa=row[6],
            english_meaning=row[7],
            plural_form=row[8],
            verb_forms=row[9],
            comparative=row[10],
            collocation_de=row[11] if len(row) > 11 else None,
            collocation_fa=row[12] if len(row) > 12 else None,
        )

    def get_by_id(self, word_id: int) -> Optional[Word]:
        """Get a word by its ID."""
        with self.db._cursor() as c:
            c.execute(f"SELECT {self._word_columns()} FROM words WHERE id = ?", (word_id,))
            row = c.fetchone()
            return self._row_to_word(row) if row else None

    def get_by_ids(self, word_ids: List[int]) -> List[Word]:
        """Get multiple words by their IDs."""
        if not word_ids:
            return []

        placeholders = ",".join("?" for _ in word_ids)
        with self.db._cursor() as c:
            c.execute(
                f"SELECT {self._word_columns()} FROM words WHERE id IN ({placeholders})",
                tuple(word_ids),
            )
            rows = c.fetchall()

        by_id = {row[0]: self._row_to_word(row) for row in rows}
        return [by_id[wid] for wid in word_ids if wid in by_id]

    def _not_in_clause(self, exclude_ids: Optional[Iterable[int]], column: str = "id") -> Tuple[str, List[int]]:
        """Generate a NOT IN clause for excluding IDs."""
        ids = list(set(exclude_ids or []))
        if not ids:
            return "", []
        placeholders = ",".join("?" for _ in ids)
        return f" AND {column} NOT IN ({placeholders})", ids

    def get_new_words(
        self,
        user_id: int,
        lesson_id: Optional[int] = None,
        limit: int = 10,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get new words that haven't been studied yet."""
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)

        if lesson_id:
            query = f"""
                SELECT {self._word_columns()}
                FROM words
                WHERE lesson_id = ?
                AND id NOT IN (
                    SELECT word_id FROM word_stats WHERE user_id = ?
                ){exclude_clause}
                LIMIT ?
            """
            params = (lesson_id, user_id, *exclude_params, limit)
        else:
            query = f"""
                SELECT {self._word_columns()}
                FROM words
                WHERE id NOT IN (
                    SELECT word_id FROM word_stats WHERE user_id = ?
                ){exclude_clause}
                LIMIT ?
            """
            params = (user_id, *exclude_params, limit)

        with self.db._cursor() as c:
            c.execute(query, params)
            rows = c.fetchall()
            return [self._row_to_word(row) for row in rows]

    def get_due_words(
        self,
        user_id: int,
        limit: int = 10,
        lesson_id: Optional[int] = None,
        include_new: bool = True,
        new_limit: int = 5,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get words due for review based on SRS schedule."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)

        if lesson_id:
            # Get due words from specific lesson
            due_query = f"""
                SELECT w.{self._word_columns('w')}
                FROM words w
                JOIN word_stats ws ON ws.word_id = w.id
                WHERE ws.user_id = ?
                AND w.lesson_id = ?
                AND ws.phase != 'new'
                AND (ws.next_review IS NULL OR ws.next_review <= ?)
                {exclude_clause}
                ORDER BY ws.next_review ASC, ws.srs_level ASC
                LIMIT ?
            """
            due_params = (user_id, lesson_id, now, *exclude_params, limit)
        else:
            # Get due words from all lessons
            due_query = f"""
                SELECT w.{self._word_columns('w')}
                FROM words w
                JOIN word_stats ws ON ws.word_id = w.id
                WHERE ws.user_id = ?
                AND ws.phase != 'new'
                AND (ws.next_review IS NULL OR ws.next_review <= ?)
                {exclude_clause}
                ORDER BY ws.next_review ASC, ws.srs_level ASC
                LIMIT ?
            """
            due_params = (user_id, now, *exclude_params, limit)

        with self.db._cursor() as c:
            c.execute(due_query, due_params)
            due_rows = c.fetchall()

        # Include new words if requested
        new_words = []
        if include_new and len(due_rows) < limit:
            remaining = limit - len(due_rows)
            new_words = self.get_new_words(user_id, lesson_id, min(new_limit, remaining), exclude_ids)

        due_words = [self._row_to_word(row) for row in due_rows]
        return due_words + new_words

    def get_flashcard_words(
        self,
        user_id: int,
        limit: int = 20,
        lesson_id: Optional[int] = None,
        include_new: bool = True,
        new_limit: int = 5,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get words for flashcard session."""
        return self.get_due_words(
            user_id=user_id,
            limit=limit,
            lesson_id=lesson_id,
            include_new=include_new,
            new_limit=new_limit,
            exclude_ids=exclude_ids,
        )

    def count_due(self, user_id: int) -> int:
        """Count words due for review."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self.db._cursor() as c:
            c.execute(
                """
                SELECT COUNT(*) FROM word_stats
                WHERE user_id = ? AND phase != 'new'
                AND (next_review IS NULL OR next_review <= ?)
                """,
                (user_id, now),
            )
            return c.fetchone()[0]

    def count_hard_due(self, user_id: int) -> int:
        """Count hard/difficult words due for review."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self.db._cursor() as c:
            c.execute(
                """
                SELECT COUNT(*) FROM word_stats
                WHERE user_id = ? AND phase != 'new'
                AND (next_review IS NULL OR next_review <= ?)
                AND difficulty >= 7.0
                """,
                (user_id, now),
            )
            return c.fetchone()[0]

    def count_weak(self, user_id: int) -> int:
        """Count weak words (low correctness rate)."""
        with self.db._cursor() as c:
            c.execute(
                """
                SELECT COUNT(*) FROM word_stats
                WHERE user_id = ? AND correct_count + wrong_count > 0
                AND CAST(correct_count AS FLOAT) / (correct_count + wrong_count) < 0.6
                """,
                (user_id,),
            )
            return c.fetchone()[0]

    def get_stats_full(self, user_id: int, word_id: int) -> Optional[Dict]:
        """Get full statistics for a word."""
        with self.db._cursor() as c:
            c.execute(
                """
                SELECT correct_count, wrong_count, ease_factor, interval_days,
                       srs_level, phase, stability, difficulty, last_reviewed, next_review
                FROM word_stats
                WHERE user_id = ? AND word_id = ?
                """,
                (user_id, word_id),
            )
            row = c.fetchone()
            if not row:
                return None
            return {
                "correct": row[0],
                "wrong": row[1],
                "ease": row[2],
                "interval": row[3],
                "srs_level": row[4],
                "phase": row[5],
                "stability": row[6],
                "difficulty": row[7],
                "last_reviewed": row[8],
                "next_review": row[9],
            }

    def update_stats_fsrs(
        self,
        user_id: int,
        word_id: int,
        correct: int,
        wrong: int,
        ease_factor: float,
        interval_days: int,
        srs_level: int,
        last_review: str,
        next_review: str,
        phase: str,
        stability: float,
        difficulty: float,
    ) -> None:
        """Update word statistics using FSRS algorithm."""
        with self.db._cursor(commit=True) as c:
            # Check if stats exist
            c.execute(
                "SELECT id FROM word_stats WHERE user_id = ? AND word_id = ?",
                (user_id, word_id),
            )
            exists = c.fetchone()

            if exists:
                c.execute(
                    """
                    UPDATE word_stats SET
                    correct_count = correct_count + ?,
                    wrong_count = wrong_count + ?,
                    ease_factor = ?,
                    interval_days = ?,
                    srs_level = ?,
                    last_reviewed = ?,
                    next_review = ?,
                    phase = ?,
                    stability = ?,
                    difficulty = ?
                    WHERE user_id = ? AND word_id = ?
                    """,
                    (
                        correct, wrong, ease_factor, interval_days, srs_level,
                        last_review, next_review, phase, stability, difficulty,
                        user_id, word_id,
                    ),
                )
            else:
                c.execute(
                    """
                    INSERT INTO word_stats (
                        user_id, word_id, correct_count, wrong_count,
                        ease_factor, interval_days, srs_level, last_reviewed,
                        next_review, phase, stability, difficulty
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, word_id, correct, wrong,
                        ease_factor, interval_days, srs_level, last_review,
                        next_review, phase, stability, difficulty,
                    ),
                )
