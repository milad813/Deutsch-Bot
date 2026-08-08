"""Word repository for word-related database operations."""

import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from database.connection import DatabaseConnection
from database.repositories.base import BaseRepository
from models import Word

logger = logging.getLogger(__name__)


class WordRepository(BaseRepository):
    """Repository for word CRUD operations and queries."""

    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def _word_columns(self, alias: Optional[str] = None) -> str:
        """Generate column list for word queries."""
        prefix = f"{alias}." if alias else ""
        return f"""
            {prefix}id, {prefix}user_id, {prefix}book_id, {prefix}lesson_id,
            {prefix}article, {prefix}german, {prefix}persian,
            {prefix}english_meaning, {prefix}word_type, {prefix}plural_form,
            {prefix}verb_forms, {prefix}comparative, {prefix}example_de,
            {prefix}example_fa, {prefix}created_at
        """

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
            created_at=row[13] if len(row) > 13 else None,
        )

    def get_by_id(self, word_id: int) -> Optional[Word]:
        """Get a word by its ID."""
        query = f"SELECT {self._word_columns()} FROM words WHERE id = ?"
        row = self.fetch_one(query, (word_id,))
        return self._row_to_word(row) if row else None

    def get_by_ids(self, word_ids: List[int]) -> List[Word]:
        """Get multiple words by their IDs."""
        if not word_ids:
            return []

        placeholders = ",".join("?" for _ in word_ids)
        query = f"SELECT {self._word_columns()} FROM words WHERE id IN ({placeholders})"
        rows = self.fetch_all(query, tuple(word_ids))
        return [self._row_to_word(row) for row in rows]

    def get_all(self) -> List[Word]:
        """Get all words from the database."""
        query = f"SELECT {self._word_columns()} FROM words"
        rows = self.fetch_all(query)
        return [self._row_to_word(row) for row in rows]

    def get_by_type(
        self, word_type: str, limit: int = 50, exclude_ids: Optional[List[int]] = None
    ) -> List[Word]:
        """Get words by type with optional exclusions."""
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)
        query = f"""
            SELECT {self._word_columns()}
            FROM words
            WHERE word_type = ?{exclude_clause}
            LIMIT ?
        """
        params = (word_type,) + tuple(exclude_params) + (limit,)
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def get_by_lesson_full(self, lesson_id: int) -> List[Dict]:
        """Get all words for a lesson with full details."""
        query = f"""
            SELECT {self._word_columns()}
            FROM words
            WHERE lesson_id = ?
            ORDER BY german
        """
        rows = self.fetch_all(query, (lesson_id,))
        return [self._row_to_word(row).to_dict() for row in rows]

    def get_without_collocation(self, limit: int = 200) -> List[Dict]:
        """Get words that don't have collocations yet."""
        query = f"""
            SELECT {self._word_columns()}
            FROM words
            WHERE (collocation_de IS NULL OR collocation_de = '')
            LIMIT ?
        """
        rows = self.fetch_all(query, (limit,))
        return [self._row_to_word(row).to_dict() for row in rows]

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
        logger.info("Updated collocation for word %d", word_id)

    def get_count(self) -> int:
        """Get total word count."""
        row = self.fetch_one("SELECT COUNT(*) FROM words")
        return row[0] if row else 0

    def get_count_by_lesson(self, lesson_id: int) -> int:
        """Get word count for a specific lesson."""
        query = "SELECT COUNT(*) FROM words WHERE lesson_id = ?"
        row = self.fetch_one(query, (lesson_id,))
        return row[0] if row else 0

    def get_random(
        self, limit: int = 1, exclude_ids: Optional[List[int]] = None
    ) -> List[Word]:
        """Get random words with optional exclusions."""
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)
        query = f"""
            SELECT {self._word_columns()}
            FROM words
            WHERE 1=1{exclude_clause}
            ORDER BY RANDOM()
            LIMIT ?
        """
        params = tuple(exclude_params) + (limit,)
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def get_nouns_with_article(
        self, limit: int = 50, exclude_ids: Optional[List[int]] = None
    ) -> List[Word]:
        """Get nouns that have articles."""
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)
        query = f"""
            SELECT {self._word_columns()}
            FROM words
            WHERE word_type = 'noun' AND article IS NOT NULL{exclude_clause}
            ORDER BY RANDOM()
            LIMIT ?
        """
        params = tuple(exclude_params) + (limit,)
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def get_with_example(
        self, limit: int = 50, exclude_ids: Optional[List[int]] = None
    ) -> List[Word]:
        """Get words that have example sentences."""
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)
        query = f"""
            SELECT {self._word_columns()}
            FROM words
            WHERE example_de IS NOT NULL AND example_fa IS NOT NULL{exclude_clause}
            ORDER BY RANDOM()
            LIMIT ?
        """
        params = tuple(exclude_params) + (limit,)
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def get_new_words(
        self, user_id: int, limit: int = 20, exclude_ids: Optional[List[int]] = None
    ) -> List[Word]:
        """Get new words for a user (not yet in SRS)."""
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            LEFT JOIN word_stats ws ON w.id = ws.word_id AND ws.user_id = ?
            WHERE ws.word_id IS NULL{exclude_clause}
            ORDER BY RANDOM()
            LIMIT ?
        """
        params = (user_id,) + tuple(exclude_params) + (limit,)
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def get_due_words(
        self, user_id: int, limit: int = 20, exclude_ids: Optional[List[int]] = None
    ) -> List[Word]:
        """Get words due for review based on SRS."""
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)
        now = datetime.now(timezone.utc).isoformat()
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
            AND ws.next_review <= ?{exclude_clause}
            ORDER BY ws.next_review ASC
            LIMIT ?
        """
        params = (user_id, now) + tuple(exclude_params) + (limit,)
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def get_weak_words(
        self, user_id: int, limit: int = 20, exclude_ids: Optional[List[int]] = None
    ) -> List[Word]:
        """Get words marked as weak/difficult."""
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
            AND ws.strength < 0.5{exclude_clause}
            ORDER BY ws.strength ASC
            LIMIT ?
        """
        params = (user_id,) + tuple(exclude_params) + (limit,)
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def get_weak_by_lesson(
        self, user_id: int, lesson_id: int, limit: int = 20
    ) -> List[Word]:
        """Get weak words for a specific lesson."""
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
            AND w.lesson_id = ?
            AND ws.strength < 0.5
            ORDER BY ws.strength ASC
            LIMIT ?
        """
        params = (user_id, lesson_id, limit)
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def get_flashcard_words(
        self, user_id: int, lesson_id: Optional[int] = None, limit: int = 20,
        include_new: bool = False, new_limit: int = 5, exclude_ids: Optional[list] = None
    ) -> List[Word]:
        """Get words for flashcard practice."""
        # Get reviewed words (words with stats)
        if lesson_id:
            query = f"""
                SELECT {self._word_columns('w')}, ws.next_review, ws.strength
                FROM words w
                JOIN word_stats ws ON w.id = ws.word_id
                WHERE ws.user_id = ? AND w.lesson_id = ?
                AND ws.next_review <= datetime('now')
                ORDER BY ws.next_review ASC
                LIMIT ?
            """
            params = (user_id, lesson_id, limit)
        else:
            query = f"""
                SELECT {self._word_columns('w')}, ws.next_review, ws.strength
                FROM words w
                JOIN word_stats ws ON w.id = ws.word_id
                WHERE ws.user_id = ?
                AND ws.next_review <= datetime('now')
                ORDER BY ws.next_review ASC
                LIMIT ?
            """
            params = (user_id, limit)

        rows = self.fetch_all(query, params)
        words = [self._row_to_word(row) for row in rows]
        
        # If include_new is True, add new words
        if include_new and len(words) < limit:
            remaining = limit - len(words)
            new_words = self.get_new_word_objects(
                user_id=user_id,
                lesson_id=lesson_id,
                limit=remaining,
                exclude_ids=[w.id for w in words] + (exclude_ids or [])
            )
            words.extend(new_words)
        
        return words[:limit]

    def get_new_word_objects(
        self, user_id: int, lesson_id: Optional[int] = None, limit: int = 20,
        exclude_ids: Optional[list] = None
    ) -> List[Word]:
        """Get new words for learning."""
        exclude_clause = ""
        params_list = [user_id]
        
        if lesson_id:
            params_list.append(lesson_id)
            lesson_filter = "AND w.lesson_id = ?"
        else:
            lesson_filter = ""
            
        if exclude_ids:
            placeholders = ','.join('?' * len(exclude_ids))
            exclude_clause = f"AND w.id NOT IN ({placeholders})"
            params_list.extend(exclude_ids)
        
        params = tuple(params_list) + (limit,)
        
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            LEFT JOIN word_stats ws ON w.id = ws.word_id AND ws.user_id = ?
            WHERE w.user_id = ? {lesson_filter}
            AND (ws.word_id IS NULL OR ws.reviews = 0)
            {exclude_clause}
            ORDER BY RANDOM()
            LIMIT ?
        """
        
        # Rebuild params with the user_id repeated for the JOIN condition
        if lesson_id:
            params = (user_id, user_id, lesson_id) + (tuple(exclude_ids) if exclude_ids else ()) + (limit,)
        else:
            params = (user_id, user_id) + (tuple(exclude_ids) if exclude_ids else ()) + (limit,)
            
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def get_due_today(self, user_id: int) -> List[Tuple]:
        """Get words due for review today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        query = f"""
            SELECT {self._word_columns('w')}, ws.next_review, ws.strength
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
            AND DATE(ws.next_review) = ?
        """
        return self.fetch_all(query, (user_id, today))

    def get_due_count(self, user_id: int) -> int:
        """Get count of words due for review."""
        now = datetime.now(timezone.utc).isoformat()
        query = """
            SELECT COUNT(*) FROM word_stats
            WHERE user_id = ? AND next_review <= ?
        """
        row = self.fetch_one(query, (user_id, now))
        return row[0] if row else 0

    def get_weak_count(self, user_id: int) -> int:
        """Get count of weak words."""
        query = """
            SELECT COUNT(*) FROM word_stats
            WHERE user_id = ? AND strength < 0.5
        """
        row = self.fetch_one(query, (user_id,))
        return row[0] if row else 0

    def update_srs_stats(
        self,
        user_id: int,
        word_id: int,
        strength: float,
        next_review: datetime,
        phase: str,
        correct_answers: int = 0,
        incorrect_answers: int = 0,
    ) -> None:
        """Update SRS statistics for a word."""
        query = """
            INSERT INTO word_stats
            (user_id, word_id, strength, next_review, phase, correct_answers, incorrect_answers)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, word_id) DO UPDATE SET
            strength = excluded.strength,
            next_review = excluded.next_review,
            phase = excluded.phase,
            correct_answers = correct_answers + excluded.correct_answers,
            incorrect_answers = incorrect_answers + excluded.incorrect_answers
        """
        params = (
            user_id,
            word_id,
            strength,
            next_review.isoformat(),
            phase,
            correct_answers,
            incorrect_answers,
        )
        self.execute(query, params, commit=True)
        logger.debug("Updated SRS stats for user %d, word %d", user_id, word_id)

    def get_hard_due_words(
        self, user_id: int, limit: int = 20, exclude_ids: Optional[List[int]] = None
    ) -> List[Word]:
        """Get hard words that are due for review."""
        exclude_clause, exclude_params = self._not_in_clause(exclude_ids)
        now = datetime.now(timezone.utc).isoformat()
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
            AND ws.next_review <= ?
            AND ws.strength < 0.3{exclude_clause}
            ORDER BY ws.next_review ASC, ws.strength ASC
            LIMIT ?
        """
        params = (user_id, now) + tuple(exclude_params) + (limit,)
        rows = self.fetch_all(query, params)
        return [self._row_to_word(row) for row in rows]

    def count_hard_due_words(self, user_id: int) -> int:
        """Count hard words due for review."""
        now = datetime.now(timezone.utc).isoformat()
        query = """
            SELECT COUNT(*) FROM word_stats
            WHERE user_id = ? AND next_review <= ? AND strength < 0.3
        """
        row = self.fetch_one(query, (user_id, now))
        return row[0] if row else 0

    def get_stats(self, user_id: int, word_id: int) -> Optional[Dict]:
        """Get statistics for a specific word."""
        query = """
            SELECT ws.*, w.german, w.persian
            FROM word_stats ws
            JOIN words w ON ws.word_id = w.id
            WHERE ws.user_id = ? AND ws.word_id = ?
        """
        row = self.fetch_one(query, (user_id, word_id))
        if not row:
            return None

        return {
            "id": row[0],
            "user_id": row[1],
            "word_id": row[2],
            "strength": row[3],
            "next_review": row[4],
            "phase": row[5],
            "correct_answers": row[6],
            "incorrect_answers": row[7],
            "german": row[8],
            "persian": row[9],
        }

    def upsert(
        self,
        user_id: int,
        book_id: Optional[int],
        lesson_id: Optional[int],
        german: str,
        persian: str,
        article: Optional[str] = None,
        english_meaning: Optional[str] = None,
        word_type: Optional[str] = None,
        plural_form: Optional[str] = None,
        verb_forms: Optional[str] = None,
        comparative: Optional[str] = None,
        example_de: Optional[str] = None,
        example_fa: Optional[str] = None,
    ) -> int:
        """Insert or update a word."""
        query = """
            INSERT INTO words
            (user_id, book_id, lesson_id, article, german, persian,
             english_meaning, word_type, plural_form, verb_forms,
             comparative, example_de, example_fa)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(german, book_id, lesson_id) DO UPDATE SET
            persian = excluded.persian,
            article = excluded.article,
            english_meaning = excluded.english_meaning,
            word_type = excluded.word_type,
            plural_form = excluded.plural_form,
            verb_forms = excluded.verb_forms,
            comparative = excluded.comparative,
            example_de = excluded.example_de,
            example_fa = excluded.example_fa
        """
        params = (
            user_id,
            book_id,
            lesson_id,
            article,
            german,
            persian,
            english_meaning,
            word_type,
            plural_form,
            verb_forms,
            comparative,
            example_de,
            example_fa,
        )
        return self.insert(query, params)
