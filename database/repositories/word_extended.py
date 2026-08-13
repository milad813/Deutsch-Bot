"""Extended WordRepository methods for complex queries."""

from typing import Dict, Iterable, List, Optional, Tuple

from database.connection import DEFAULT_OWNER_ID, DatabaseConnection
from database.repositories.base import BaseRepository
from models import Word


class ExtendedWordRepository(BaseRepository):

    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def _word_columns(self, alias: Optional[str] = None) -> str:
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
        return Word(
            id=row[0],
            german=row[5],
            persian=row[6],
            article=row[4],
            word_type=row[8],
            example_de=row[12],
            example_fa=row[13],
            english_meaning=row[7],
            plural_form=row[9],
            verb_forms=row[10],
            comparative=row[11],
            collocation_de=row[15],
            collocation_fa=row[16],
        )

    # ─── Simple queries ───

    def get_by_id(self, word_id: int) -> Optional[Word]:
        query = f"SELECT {self._word_columns()} FROM words WHERE id = ?"
        row = self.fetch_one(query, (word_id,))
        return self._row_to_word(row) if row else None

    def get_by_ids(self, word_ids: List[int]) -> List[Word]:
        if not word_ids:
            return []
        placeholders = ",".join("?" for _ in word_ids)
        query = f"SELECT {self._word_columns()} FROM words WHERE id IN ({placeholders})"
        rows = self.fetch_all(query, tuple(word_ids))
        by_id = {row[0]: self._row_to_word(row) for row in rows}
        return [by_id[wid] for wid in word_ids if wid in by_id]

    def get_by_type(
        self,
        word_type: Optional[str],
        exclude_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[Word]:
        query = f"SELECT {self._word_columns()} FROM words WHERE 1=1"
        params: List = []
        if word_type:
            query += " AND word_type = ?"
            params.append(word_type)
        if exclude_id is not None:
            query += " AND id != ?"
            params.append(exclude_id)
        query += " ORDER BY RANDOM() LIMIT ?"
        params.append(limit)
        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def get_mistake_words(
        self, user_id: int, limit: int = 30, exclude_ids=None
    ) -> List[Word]:
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            WHERE w.id IN (
                SELECT ms.word_id FROM mistake_stats ms
                WHERE ms.user_id = ? AND ms.resolved_at IS NULL AND ms.wrong_count > 0
                GROUP BY ms.word_id
                ORDER BY SUM(ms.wrong_count) DESC, MAX(ms.last_wrong_at) DESC
                LIMIT ?
            )
            {exclude_sql}
            ORDER BY RANDOM() LIMIT ?
        """
        params = [user_id, limit] + exclude_params + [limit]
        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def get_weak_by_lesson(
        self,
        user_id: int,
        lesson_id: int,
        limit: int = 10,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ? AND w.lesson_id = ? AND ws.wrong_count > ws.correct_count
        """
        params: List = [user_id, lesson_id]
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql
        query += " ORDER BY ws.wrong_count DESC LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)
        rows = self.fetch_all(query, tuple(params))
        return [self._row_to_word(row) for row in rows]

    def upsert_word(
        self,
        german_word,
        persian_meaning,
        book_id=None,
        lesson_id=None,
        article=None,
        english_meaning=None,
        word_type=None,
        plural_form=None,
        verb_forms=None,
        comparative=None,
        example_de=None,
        example_fa=None,
        collocation_de=None,
        collocation_fa=None,
        cefr_estimated=None,
        topics=None,
        contexts=None,
        common_situations=None,
        story_roles=None,
        related_words=None,
        common_collocations_de=None,
        story_suitability=None,
        story_suitability_reason=None,
    ) -> int:
        book_val = book_id if book_id is not None else -1
        lesson_val = lesson_id if lesson_id is not None else -1
        check_sql = """SELECT id FROM words WHERE german = ? AND COALESCE(book_id,-1) = ? AND COALESCE(lesson_id,-1) = ?"""
        check_params = (german_word, book_val, lesson_val)
        update_sql = """
            UPDATE words SET book_id=?, lesson_id=?, article=?, german=?, persian=?,
            english_meaning=?, word_type=?, plural_form=?, verb_forms=?, comparative=?,
            example_de=?, example_fa=?, collocation_de=?, collocation_fa=?,
            cefr_estimated=?, topics=?, contexts=?, common_situations=?, story_roles=?,
            related_words=?, common_collocations_de=?, story_suitability=?, story_suitability_reason=?
            WHERE id = ?
        """
        insert_sql = """
            INSERT INTO words (user_id, book_id, lesson_id, article, german, persian,
            english_meaning, word_type, plural_form, verb_forms, comparative,
            example_de, example_fa, collocation_de, collocation_fa,
            cefr_estimated, topics, contexts, common_situations, story_roles,
            related_words, common_collocations_de, story_suitability, story_suitability_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        update_params = (
            book_id,
            lesson_id,
            article,
            german_word,
            persian_meaning,
            english_meaning,
            word_type,
            plural_form,
            verb_forms,
            comparative,
            example_de,
            example_fa,
            collocation_de,
            collocation_fa,
            cefr_estimated,
            topics,
            contexts,
            common_situations,
            story_roles,
            related_words,
            common_collocations_de,
            story_suitability,
            story_suitability_reason,
        )
        row = self.fetch_one(check_sql, check_params)
        if row:
            word_id = row[0]
            self.execute(update_sql, update_params + (word_id,), commit=True)
            return word_id
        try:
            insert_params = (
                DEFAULT_OWNER_ID,
                book_id,
                lesson_id,
                article,
                german_word,
                persian_meaning,
                english_meaning,
                word_type,
                plural_form,
                verb_forms,
                comparative,
                example_de,
                example_fa,
                collocation_de,
                collocation_fa,
                cefr_estimated,
                topics,
                contexts,
                common_situations,
                story_roles,
                related_words,
                common_collocations_de,
                story_suitability,
                story_suitability_reason,
            )
            return self.insert(insert_sql, insert_params)
        except Exception:
            row2 = self.fetch_one(check_sql, check_params)
            if not row2:
                raise
            word_id = row2[0]
            self.execute(update_sql, update_params + (word_id,), commit=True)
            return word_id

    # ─── درس / آمار ───

    def get_by_lesson_full(self, lesson_id: int) -> List[Dict]:
        query = """
            SELECT id, article, german, persian, word_type,
            plural_form, verb_forms, comparative, example_de, example_fa,
            english_meaning, collocation_de, collocation_fa
            FROM words WHERE lesson_id = ? ORDER BY word_type, german
        """
        rows = self.fetch_all(query, (lesson_id,))
        return [
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
            for r in rows
        ]

    def get_without_collocation(self, limit: int = 200) -> List[Dict]:
        query = """SELECT id, german, persian, article, word_type FROM words
                   WHERE (collocation_de IS NULL OR collocation_de = '') ORDER BY id LIMIT ?"""
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
        self.execute(
            "UPDATE words SET collocation_de=?, collocation_fa=? WHERE id=?",
            (collocation_de, collocation_fa, word_id),
            commit=True,
        )

    def get_count(self) -> int:
        row = self.fetch_one("SELECT COUNT(*) FROM words")
        return row[0] if row else 0

    def get_count_by_lesson(self, lesson_id: int) -> int:
        row = self.fetch_one(
            "SELECT COUNT(*) FROM words WHERE lesson_id=?", (lesson_id,)
        )
        return row[0] if row else 0

    def get_random(
        self, lesson_id: int = None, exclude_ids: Optional[Iterable[int]] = None
    ) -> Optional[Word]:
        query = f"SELECT {self._word_columns()} FROM words WHERE 1=1"
        params = []
        if lesson_id:
            query += " AND lesson_id = ?"
            params.append(lesson_id)
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "id")
        query += exclude_sql + " ORDER BY RANDOM() LIMIT 1"
        params.extend(exclude_params)
        row = self.fetch_one(query, tuple(params))
        return self._row_to_word(row) if row else None

    def get_nouns_with_article(
        self,
        lesson_id: int = None,
        limit: int = 100,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        query = f"SELECT {self._word_columns()} FROM words WHERE article IS NOT NULL AND article != ''"
        params = []
        if lesson_id:
            query += " AND lesson_id = ?"
            params.append(lesson_id)
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "id")
        query += exclude_sql + " ORDER BY RANDOM() LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)
        return [self._row_to_word(row) for row in self.fetch_all(query, tuple(params))]

    def get_with_examples(
        self, lesson_id: int = None, exclude_ids: Optional[Iterable[int]] = None
    ) -> List[Word]:
        query = f"SELECT {self._word_columns()} FROM words WHERE example_de IS NOT NULL AND example_de != ''"
        params = []
        if lesson_id:
            query += " AND lesson_id = ?"
            params.append(lesson_id)
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "id")
        query += exclude_sql + " ORDER BY RANDOM()"
        params.extend(exclude_params)
        return [self._row_to_word(row) for row in self.fetch_all(query, tuple(params))]

    def get_new(
        self,
        user_id: int,
        lesson_id: int = None,
        limit: int = 20,
        exclude_ids: Optional[Iterable[int]] = None,
        only_studied_lessons: bool = True,
    ) -> List[Word]:
        query = f"""SELECT {self._word_columns('w')} FROM words w
                    LEFT JOIN word_stats ws ON ws.word_id = w.id AND ws.user_id = ?
                    WHERE ws.word_id IS NULL"""
        if lesson_id is None and only_studied_lessons:
            row = self.fetch_one(
                "SELECT COUNT(*) FROM word_stats WHERE user_id=?", (user_id,)
            )
            if not row or (row[0] or 0) == 0:
                only_studied_lessons = False
        params: List = [user_id]
        if lesson_id:
            query += " AND w.lesson_id = ?"
            params.append(lesson_id)
        elif only_studied_lessons:
            query += """ AND w.lesson_id IN (
                SELECT DISTINCT w2.lesson_id FROM words w2
                JOIN word_stats ws2 ON ws2.word_id = w2.id AND ws2.user_id = ?
                WHERE w2.lesson_id IS NOT NULL)"""
            params.append(user_id)
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql + """ ORDER BY 
            CASE w.cefr_estimated 
                WHEN 'A1' THEN 1 
                WHEN 'A2' THEN 2 
                WHEN 'B1' THEN 3 
                WHEN 'B2' THEN 4 
                ELSE 5 
            END, 
            w.id ASC 
        LIMIT ?"""
        params.extend(exclude_params)
        params.append(limit)
        return [self._row_to_word(row) for row in self.fetch_all(query, tuple(params))]

    def get_due(
        self,
        user_id: int,
        limit: int = 20,
        lesson_id: int = None,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        query = f"""SELECT {self._word_columns('w')} FROM words w
                    JOIN word_stats ws ON w.id = ws.word_id
                    WHERE ws.user_id = ? AND ws.next_review <= datetime('now')"""
        params = [user_id]
        if lesson_id:
            query += " AND w.lesson_id = ?"
            params.append(lesson_id)
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql + " ORDER BY ws.next_review ASC LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)
        return [self._row_to_word(row) for row in self.fetch_all(query, tuple(params))]

    def get_weak(
        self, user_id: int, limit: int = 20, exclude_ids: Optional[Iterable[int]] = None
    ) -> List[Word]:
        query = f"""SELECT {self._word_columns('w')} FROM words w
                    JOIN word_stats ws ON w.id = ws.word_id
                    WHERE ws.user_id = ? AND ws.wrong_count > ws.correct_count"""
        params = [user_id]
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql + " ORDER BY ws.wrong_count DESC LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)
        return [self._row_to_word(row) for row in self.fetch_all(query, tuple(params))]

    def get_for_flashcard(
        self,
        user_id: int,
        limit: int = 10,
        lesson_id: int = None,
        include_new: bool = True,
        new_limit: int = 5,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        exclude_ids = set(exclude_ids or [])
        due_words = self.get_due(
            user_id=user_id, limit=limit, lesson_id=lesson_id, exclude_ids=exclude_ids
        )
        result = list(due_words)
        exclude_ids.update(w.id for w in result)
        if include_new and len(result) < limit:
            remaining_new = min(new_limit, limit - len(result))
            if remaining_new > 0:
                result.extend(
                    self.get_new(
                        user_id=user_id,
                        lesson_id=lesson_id,
                        limit=remaining_new,
                        exclude_ids=exclude_ids,
                    )
                )
        return result

    # ─── Aliasها ───

    def get_flashcard_words(
        self,
        user_id,
        lesson_id=None,
        limit=20,
        include_new=False,
        new_limit=5,
        exclude_ids=None,
    ):
        return self.get_for_flashcard(
            user_id,
            limit=limit,
            lesson_id=lesson_id,
            include_new=include_new,
            new_limit=new_limit,
            exclude_ids=exclude_ids,
        )

    def get_new_word_objects(self, user_id, lesson_id=None, limit=20, exclude_ids=None):
        return self.get_new(
            user_id,
            lesson_id=lesson_id,
            limit=limit,
            exclude_ids=exclude_ids,
        )
    def get_due_today(self, user_id: int) -> List[Tuple]:
        query = """SELECT w.id, w.german, w.persian FROM words w
                   JOIN word_stats ws ON w.id = ws.word_id
                   WHERE ws.user_id = ? AND ws.next_review <= datetime('now')
                   ORDER BY ws.next_review ASC"""
        return self.fetch_all(query, (user_id,))

    def get_due_count(self, user_id: int) -> int:
        row = self.fetch_one(
            """SELECT COUNT(*) FROM words w JOIN word_stats ws ON w.id=ws.word_id
                                WHERE ws.user_id=? AND ws.next_review <= datetime('now')""",
            (user_id,),
        )
        return row[0] if row else 0

    def get_weak_count(self, user_id: int) -> int:
        row = self.fetch_one(
            """SELECT COUNT(*) FROM words w JOIN word_stats ws ON w.id=ws.word_id
                                WHERE ws.user_id=? AND ws.wrong_count > ws.correct_count""",
            (user_id,),
        )
        return row[0] if row else 0

    def get_hard_due(self, user_id, limit=20, exclude_ids=None):
        query = f"""SELECT {self._word_columns('w')} FROM words w
                    JOIN word_stats ws ON w.id = ws.word_id
                    WHERE ws.user_id = ? AND ws.phase = 'learning' AND ws.next_review <= datetime('now')"""
        params = [user_id]
        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
        query += exclude_sql + " ORDER BY ws.next_review ASC LIMIT ?"
        params.extend(exclude_params)
        params.append(limit)
        return [self._row_to_word(row) for row in self.fetch_all(query, tuple(params))]

    def count_hard_due(self, user_id: int) -> int:
        row = self.fetch_one(
            """SELECT COUNT(*) FROM words w JOIN word_stats ws ON w.id=ws.word_id
                                WHERE ws.user_id=? AND ws.phase='learning' AND ws.next_review <= datetime('now')""",
            (user_id,),
        )
        return row[0] if row else 0

    def update_stats_fsrs(
        self,
        user_id,
        word_id,
        correct,
        wrong,
        ease_factor,
        interval_days,
        srs_level,
        last_review,
        next_review,
        phase="review",
        stability=0.0,
        difficulty=0.0,
    ):
        result = self.fetch_one(
            "SELECT correct_count, wrong_count FROM word_stats WHERE user_id=? AND word_id=?",
            (user_id, word_id),
        )
        if result:
            self.execute(
                """UPDATE word_stats SET correct_count=?, wrong_count=?, ease_factor=?, interval_days=?,
                            srs_level=?, last_reviewed=?, next_review=?, phase=?, stability=?, difficulty=?
                            WHERE user_id=? AND word_id=?""",
                (
                    result[0] + correct,
                    result[1] + wrong,
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
            self.execute(
                """INSERT INTO word_stats (user_id, word_id, correct_count, wrong_count, ease_factor,
                            interval_days, srs_level, last_reviewed, next_review, phase, stability, difficulty)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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
        row = self.fetch_one(
            """SELECT correct_count, wrong_count, ease_factor, interval_days,
                                next_review, phase, stability, difficulty, srs_level, last_reviewed
                                FROM word_stats WHERE user_id=? AND word_id=?""",
            (user_id, word_id),
        )
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
                "last_reviewed": row[9],
            }
        return None


__all__ = ["ExtendedWordRepository"]
