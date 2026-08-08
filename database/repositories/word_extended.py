"""Extended WordRepository methods for complex queries."""

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from database.connection import DatabaseConnection
from database.repositories.base import BaseRepository
from models import Word


class ExtendedWordRepository(BaseRepository):
    """Extended repository for word operations with SRS/FSRS support."""

    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def _word_columns(self, alias: Optional[str] = None) -> str:
        """Get SQL column list for words table."""
        prefix = f"{alias}." if alias else ""
        return (
            f"{prefix}id, {prefix}user_id, {prefix}book_id, {prefix}lesson_id, "
            f"{prefix}article, {prefix}german, {prefix}persian, "
            f"{prefix}english_meaning, {prefix}word_type, {prefix}plural_form, "
            f"{prefix}verb_forms, {prefix}comparative, {prefix}example_de, "
            f"{prefix}example_fa, {prefix}created_at, {prefix}collocation_de, "
            f"{prefix}collocation_fa"
        )

    def _row_to_word(self, row: Tuple) -> Word:
        """Convert database row to Word object."""
        return Word(
            id=row[0],
            user_id=row[1],
            book_id=row[2],
            lesson_id=row[3],
            article=row[4],
            german=row[5],
            persian=row[6],
            english_meaning=row[7],
            word_type=row[8],
            plural_form=row[9],
            verb_forms=row[10],
            comparative=row[11],
            example_de=row[12],
            example_fa=row[13],
            created_at=row[14],
            collocation_de=row[15],
            collocation_fa=row[16],
        )

    def _not_in_clause(
        self, exclude_ids: Optional[Iterable[int]], column: str = "id"
    ) -> Tuple[str, List[int]]:
        """Generate SQL NOT IN clause for excluded IDs."""
        if not exclude_ids:
            return "", []

        exclude_list = list(exclude_ids)
        if not exclude_list:
            return "", []

        placeholders = ",".join("?" for _ in exclude_list)
        return f" AND {column} NOT IN ({placeholders})", exclude_list

    def get_by_lesson_full(self, lesson_id: int) -> List[Dict]:
        """Get all words for a lesson with full details."""
        query = """
            SELECT id, article, german, persian, word_type,
            plural_form, verb_forms, comparative, example_de, example_fa,
            english_meaning, collocation_de, collocation_fa
            FROM words
            WHERE lesson_id = ?
            ORDER BY word_type, german
        """
        rows = self.fetch_all(query, (lesson_id,))
        result = []
        for r in rows:
            result.append(
                {
                    "id": r[0],
                    "article": r[1],
                    "german": r[2],
                    "persian": r[3],
                    "word_type": r[4],
                    "plural": r[5],
                    "verb_forms": r[6],
                    "comparative": r[7],
                    "example_de": r[8],
                    "example_fa": r[9],
                    "english_meaning": r[10],
                    "collocation_de": r[11],
                    "collocation_fa": r[12],
                }
            )
        return result

    def get_without_collocation(self, limit: int = 200) -> List[Dict]:
        """Get words missing collocations."""
        query = """
            SELECT id, german, persian, article, word_type 
            FROM words
            WHERE (collocation_de IS NULL OR collocation_de = '')
            ORDER BY id 
            LIMIT ?
        """
        rows = self.fetch_all(query, (limit,))
        return [
            {
                "id": r[0],
                "german": r[1],
                "persian": r[2],
                "article": r[3],
                "word_type": r[4],
            }
            for r in rows
        ]

    def update_collocation(
        self, word_id: int, collocation_de: str, collocation_fa: str
    ) -> None:
        """Update collocation for a word."""
        query = """
            UPDATE words 
            SET collocation_de = ?, collocation_fa = ? 
            WHERE id = ?
        """
        self.execute(query, (collocation_de, collocation_fa, word_id), commit=True)

    def get_count(self) -> int:
        """Get total word count."""
        query = "SELECT COUNT(*) FROM words"
        row = self.fetch_one(query)
        return row[0] if row else 0

    def get_count_by_lesson(self, lesson_id: int) -> int:
        """Get word count for a specific lesson."""
        query = "SELECT COUNT(*) FROM words WHERE lesson_id = ?"
        row = self.fetch_one(query, (lesson_id,))
        return row[0] if row else 0

    def get_random(
        self,
        lesson_id: int = None,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> Optional[Word]:
        """Get a random word, optionally filtered by lesson."""
        query = f"SELECT {self._word_columns()} FROM words WHERE 1=1"
        params = []

        if lesson_id:
            query += " AND lesson_id = ?"
            params.append(lesson_id)

        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "id")
        query += exclude_sql
        query += " ORDER BY RANDOM() LIMIT 1"
        params.extend(exclude_params)

        row = self.fetch_one(query, tuple(params))
        return self._row_to_word(row) if row else None

    def get_nouns_with_article(
        self,
        lesson_id: int = None,
        limit: int = 100,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get nouns that have articles."""
        query = f"""
            SELECT {self._word_columns()}
            FROM words
            WHERE article IS NOT NULL AND article != ''
        """
        params = []

        if lesson_id:
            query += " AND lesson_id = ?"
            params.append(lesson_id)

        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "id")
        query += exclude_sql
        query += " ORDER BY RANDOM() LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)

        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def get_with_examples(
        self,
        lesson_id: int = None,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get words that have example sentences."""
        query = f"""
            SELECT {self._word_columns()}
            FROM words
            WHERE example_de IS NOT NULL AND example_de != ''
        """
        params = []

        if lesson_id:
            query += " AND lesson_id = ?"
            params.append(lesson_id)

        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "id")
        query += exclude_sql
        query += " ORDER BY RANDOM()"
        params.extend(exclude_params)

        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def get_new(
        self,
        user_id: int,
        lesson_id: int = None,
        limit: int = 20,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get new words (not yet learned) for a user."""
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            LEFT JOIN word_stats ws ON ws.word_id = w.id AND ws.user_id = ?
            WHERE ws.word_id IS NULL
        """
        params: List = [user_id]

        if lesson_id:
            query += " AND w.lesson_id = ?"
            params.append(lesson_id)

        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql
        query += " ORDER BY w.id ASC LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)

        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def get_due(
        self,
        user_id: int,
        limit: int = 20,
        lesson_id: int = None,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get words due for review."""
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
              AND ws.next_review <= datetime('now')
        """
        params = [user_id]

        if lesson_id:
            query += " AND w.lesson_id = ?"
            params.append(lesson_id)

        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql
        query += " ORDER BY ws.next_review ASC LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)

        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def get_weak(
        self,
        user_id: int,
        limit: int = 20,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get words where wrong_count > correct_count."""
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
              AND ws.wrong_count > ws.correct_count
        """
        params = [user_id]

        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql
        query += " ORDER BY ws.wrong_count DESC LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)

        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def get_weak_by_lesson(
        self,
        user_id: int,
        lesson_id: int,
        limit: int = 10,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get weak words for a specific lesson."""
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
              AND w.lesson_id = ?
              AND ws.wrong_count > ws.correct_count
        """
        params: List = [user_id, lesson_id]

        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql
        query += " ORDER BY ws.wrong_count DESC LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)

        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def get_for_flashcard(
        self,
        user_id: int,
        limit: int = 10,
        lesson_id: int = None,
        include_new: bool = True,
        new_limit: int = 5,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """Get words for flashcard session (due + new)."""
        exclude_ids = set(exclude_ids or [])

        # Get due words first
        due_words = self.get_due(
            user_id=user_id,
            limit=limit,
            lesson_id=lesson_id,
            exclude_ids=exclude_ids,
        )

        result = list(due_words)
        exclude_ids.update(w.id for w in result)

        # Add new words if needed
        if include_new and len(result) < limit:
            remaining_new = min(new_limit, limit - len(result))
            if remaining_new > 0:
                new_words = self.get_new(
                    user_id=user_id,
                    lesson_id=lesson_id,
                    limit=remaining_new,
                    exclude_ids=exclude_ids,
                )
                result.extend(new_words)

        return result

    def get_flashcard_words(
        self, user_id: int, lesson_id: Optional[int] = None, limit: int = 20,
        include_new: bool = False, new_limit: int = 5, exclude_ids: Optional[list] = None
    ) -> List[Word]:
        """Get words for flashcard practice (alias for get_for_flashcard)."""
        return self.get_for_flashcard(
            user_id=user_id,
            lesson_id=lesson_id,
            limit=limit,
            include_new=include_new,
            new_limit=new_limit,
            exclude_ids=exclude_ids,
        )

    def get_new_word_objects(
        self, user_id: int, lesson_id: Optional[int] = None, limit: int = 20,
        exclude_ids: Optional[list] = None
    ) -> List[Word]:
        """Get new words for learning (alias for get_new)."""
        return self.get_new(
            user_id=user_id,
            lesson_id=lesson_id,
            limit=limit,
            exclude_ids=exclude_ids,
        )

    def get_due_today(self, user_id: int) -> List[Tuple]:
        """Get words due today (simple format)."""
        query = """
            SELECT w.id, w.german, w.persian
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
              AND ws.next_review <= datetime('now')
            ORDER BY ws.next_review ASC
        """
        return self.fetch_all(query, (user_id,))

    def get_due_count(self, user_id: int) -> int:
        """Get count of words due for review."""
        query = """
            SELECT COUNT(*)
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
              AND ws.next_review <= datetime('now')
        """
        row = self.fetch_one(query, (user_id,))
        return row[0] if row else 0

    def get_weak_count(self, user_id: int) -> int:
        """Get count of weak words."""
        query = """
            SELECT COUNT(*)
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
              AND ws.wrong_count > ws.correct_count
        """
        row = self.fetch_one(query, (user_id,))
        return row[0] if row else 0

    def get_hard_due(
        self, user_id: int, limit: int = 20, exclude_ids: Optional[Iterable[int]] = None
    ) -> List[Word]:
        """Get hard due words (in learning phase)."""
        query = f"""
        SELECT {self._word_columns('w')}
        FROM words w
        JOIN word_stats ws ON w.id = ws.word_id
        WHERE ws.user_id = ?
        AND ws.phase = 'learning'
        AND ws.next_review <= datetime('now')
        """
        params = [user_id]
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql
        query += " ORDER BY ws.next_review ASC LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)

        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def count_hard_due(self, user_id: int) -> int:
        """Count hard due words."""
        query = """
            SELECT COUNT(*)
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
            AND ws.phase = 'learning'
            AND ws.next_review <= datetime('now')
        """
        row = self.fetch_one(query, (user_id,))
        return row[0] if row else 0

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
        phase: str = "review",
        stability: float = 0.0,
        difficulty: float = 0.0,
    ) -> None:
        """Update word stats with FSRS data."""
        # Check if stats exist
        check_query = """
            SELECT correct_count, wrong_count 
            FROM word_stats 
            WHERE user_id = ? AND word_id = ?
        """
        result = self.fetch_one(check_query, (user_id, word_id))

        if result:
            old_correct, old_wrong = result
            new_correct = old_correct + correct
            new_wrong = old_wrong + wrong

            update_query = """
                UPDATE word_stats SET
                    correct_count = ?, wrong_count = ?,
                    ease_factor = ?, interval_days = ?, srs_level = ?,
                    last_reviewed = ?, next_review = ?,
                    phase = ?, stability = ?, difficulty = ?
                WHERE user_id = ? AND word_id = ?
            """
            self.execute(
                update_query,
                (
                    new_correct,
                    new_wrong,
                    ease_factor,
                    interval_days,
                    srs_level,
                    last_review,
                    next_review,
                    phase,
                    stability,
                    difficulty,
                    user_id,
                    word_id,
                ),
                commit=True,
            )
        else:
            insert_query = """
                INSERT INTO word_stats (
                    user_id, word_id, correct_count, wrong_count,
                    ease_factor, interval_days, srs_level, last_reviewed, next_review,
                    phase, stability, difficulty
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            self.execute(
                insert_query,
                (
                    user_id,
                    word_id,
                    correct,
                    wrong,
                    ease_factor,
                    interval_days,
                    srs_level,
                    last_review,
                    next_review,
                    phase,
                    stability,
                    difficulty,
                ),
                commit=True,
            )

    def get_stats_full(self, user_id: int, word_id: int) -> Optional[Dict]:
        """Get full stats for a word."""
        query = """
            SELECT correct_count, wrong_count, ease_factor, interval_days,
                   next_review, phase, stability, difficulty, srs_level
            FROM word_stats
            WHERE user_id = ? AND word_id = ?
        """
        row = self.fetch_one(query, (user_id, word_id))

        if row:
            return {
                "correct": row[0],
                "wrong": row[1],
                "ease": row[2],
                "interval": row[3],
                "next_review": row[4],
                "phase": row[5] or "new",
                "stability": row[6] or 0.0,
                "difficulty": row[7] or 0.0,
                "srs_level": row[8] or 0,
            }

        return None


__all__ = ["ExtendedWordRepository"]
