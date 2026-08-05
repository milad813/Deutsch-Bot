import sqlite3
import os
import logging
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Iterable

from models import Word

logger = logging.getLogger(__name__)

_DEFAULT_OWNER_ID = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, db_name: str = "words.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")

        self._create_tables()
        self._migrate()
        self._create_indexes()

    @contextmanager
    def _cursor(self, commit: bool = False):
        cur = self.conn.cursor()
        try:
            yield cur
            if commit:
                self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    def _create_tables(self):
        with self._cursor(commit=True) as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    level TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    lesson_number INTEGER NOT NULL,
                    title TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (book_id) REFERENCES books(id),
                    UNIQUE(book_id, lesson_number)
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    book_id INTEGER,
                    lesson_id INTEGER,
                    article TEXT,
                    german TEXT NOT NULL,
                    persian TEXT NOT NULL,
                    english_meaning TEXT,
                    word_type TEXT,
                    plural_form TEXT,
                    verb_forms TEXT,
                    comparative TEXT,
                    example_de TEXT,
                    example_fa TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (book_id) REFERENCES books(id),
                    FOREIGN KEY (lesson_id) REFERENCES lessons(id),
                    UNIQUE(german, book_id, lesson_id)
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id INTEGER PRIMARY KEY,
                    correct_answers INTEGER DEFAULT 0,
                    total_answers INTEGER DEFAULT 0
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS word_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    word_id INTEGER NOT NULL,
                    correct_count INTEGER DEFAULT 0,
                    wrong_count INTEGER DEFAULT 0,
                    last_reviewed TIMESTAMP,
                    next_review TIMESTAMP,
                    ease_factor REAL DEFAULT 2.5,
                    interval_days INTEGER DEFAULT 0,
                    srs_level INTEGER DEFAULT 0,
                    phase TEXT DEFAULT 'new',
                    stability REAL DEFAULT 0.0,
                    difficulty REAL DEFAULT 0.0,
                    FOREIGN KEY (word_id) REFERENCES words(id),
                    UNIQUE(user_id, word_id)
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    preferred_level TEXT DEFAULT 'A1'
                )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                user_id INTEGER PRIMARY KEY,
                xp INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0,
                last_active_date TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS pending_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                due_at TEXT NOT NULL,
                UNIQUE(user_id, word_id)
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS grammar_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL,
                topic_key TEXT NOT NULL,
                title_fa TEXT,
                level TEXT,
                explanation_fa TEXT,
                rule_de TEXT,
                examples_json TEXT,
                exercises_json TEXT,
                certainty TEXT,
                note TEXT,
                FOREIGN KEY (lesson_id) REFERENCES lessons(id),
                UNIQUE(lesson_id, topic_key)
            )
            """)

            c.execute("""
            CREATE TABLE IF NOT EXISTS stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL,
                title_fa TEXT,
                text_de TEXT NOT NULL,
                text_fa TEXT,
                target_word_ids TEXT,  -- JSON array از word_idها
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lesson_id) REFERENCES lessons(id)
            )
            """)
            


    def _migrate(self):
        migrations = [
            "ALTER TABLE words ADD COLUMN book_id INTEGER",
            "ALTER TABLE words ADD COLUMN lesson_id INTEGER",
            "ALTER TABLE words ADD COLUMN article TEXT",
            "ALTER TABLE words ADD COLUMN plural_form TEXT",
            "ALTER TABLE words ADD COLUMN verb_forms TEXT",
            "ALTER TABLE words ADD COLUMN comparative TEXT",
            "ALTER TABLE words ADD COLUMN collocation_de TEXT",
            "ALTER TABLE words ADD COLUMN collocation_fa TEXT",
            "ALTER TABLE word_stats ADD COLUMN phase TEXT DEFAULT 'new'",
            "ALTER TABLE word_stats ADD COLUMN stability REAL DEFAULT 0.0",
            "ALTER TABLE word_stats ADD COLUMN difficulty REAL DEFAULT 0.0",
            "ALTER TABLE stories ADD COLUMN title_de TEXT",
            "ALTER TABLE stories ADD COLUMN questions_json TEXT",
            "ALTER TABLE stories ADD COLUMN level TEXT",
        ]
        with self._cursor(commit=True) as c:
            for sql in migrations:
                try:
                    c.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        logger.warning("Migration failed: %s", e)


    def _create_indexes(self):
        with self._cursor(commit=True) as c:
            try:
                c.execute("CREATE INDEX IF NOT EXISTS idx_words_lesson ON words(lesson_id)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_words_word_type ON words(word_type)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_word_stats_user ON word_stats(user_id, word_id)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_word_stats_next_review ON word_stats(user_id, next_review)")
                c.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_words_german_book_lesson "
                    "ON words(german, COALESCE(book_id, -1), COALESCE(lesson_id, -1))"
                )
            except sqlite3.OperationalError as e:
                logger.warning("خطا در ایجاد ایندکس: %s", e)

    def _word_columns(self, alias: Optional[str] = None) -> str:
        prefix = f"{alias}." if alias else ""
        return (
            f"{prefix}id, {prefix}german, {prefix}persian, {prefix}article, "
            f"{prefix}word_type, {prefix}example_de, {prefix}example_fa, {prefix}english_meaning, "
            f"{prefix}plural_form, {prefix}verb_forms, {prefix}comparative, "
            f"{prefix}collocation_de, {prefix}collocation_fa"
        )


    def _row_to_word(self, row: Tuple) -> Word:
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
    
    def _not_in_clause(self, exclude_ids: Optional[Iterable[int]], column: str = "id") -> Tuple[str, List[int]]:
        ids = list(set(exclude_ids or []))
        if not ids:
            return "", []

        placeholders = ",".join("?" for _ in ids)
        return f" AND {column} NOT IN ({placeholders})", ids

    # Books / Lessons

    def add_book(self, name: str, level: str = "A1") -> int:
        try:
            with self._cursor(commit=True) as c:
                c.execute("INSERT INTO books (name, level) VALUES (?, ?)", (name, level))
                return c.lastrowid
        except sqlite3.IntegrityError:
            with self._cursor() as c:
                c.execute("SELECT id FROM books WHERE name = ?", (name,))
                row = c.fetchone()
                return row[0]

    def add_lesson(self, book_id: int, lesson_number: int, title: str = None) -> int:
        try:
            with self._cursor(commit=True) as c:
                c.execute(
                    "INSERT INTO lessons (book_id, lesson_number, title) VALUES (?, ?, ?)",
                    (book_id, lesson_number, title),
                )
                return c.lastrowid
        except sqlite3.IntegrityError:
            with self._cursor() as c:
                c.execute(
                    "SELECT id FROM lessons WHERE book_id = ? AND lesson_number = ?",
                    (book_id, lesson_number),
                )
                row = c.fetchone()
                return row[0]

    def get_all_books(self) -> List[Tuple]:
        with self._cursor() as c:
            c.execute("SELECT id, name, level FROM books ORDER BY name")
            return c.fetchall()

    def get_lessons_by_book(self, book_id: int) -> List[Tuple]:
        with self._cursor() as c:
            c.execute(
                "SELECT id, lesson_number, title FROM lessons WHERE book_id = ? ORDER BY lesson_number",
                (book_id,),
            )
            return c.fetchall()

    def get_lesson(self, lesson_id: int) -> Optional[Tuple]:
        with self._cursor() as c:
            c.execute("SELECT lesson_number, title FROM lessons WHERE id = ?", (lesson_id,))
            return c.fetchone()

    def get_book_id_by_lesson(self, lesson_id: int) -> Optional[int]:
        with self._cursor() as c:
            c.execute("SELECT book_id FROM lessons WHERE id = ?", (lesson_id,))
            row = c.fetchone()
            return row[0] if row else None

    def set_lesson_title_if_empty(self, lesson_id: int, title: str):
        with self._cursor(commit=True) as c:
            c.execute(
                """
                UPDATE lessons
                SET title = ?
                WHERE id = ? AND (title IS NULL OR title = '')
                """,
                (title, lesson_id),
            )

    # Words
    def get_book_level_by_lesson(self, lesson_id: int) -> Optional[str]:
        with self._cursor() as c:
            c.execute(
                """
                SELECT b.level
                FROM lessons l
                JOIN books b ON b.id = l.book_id
                WHERE l.id = ?
                """,
                (lesson_id,),
            )
            row = c.fetchone()
            return row[0] if row else None

    def upsert_word(
        self,
        german_word: str,
        persian_meaning: str,
        book_id: int = None,
        lesson_id: int = None,
        article: str = None,
        english_meaning: str = None,
        word_type: str = None,
        plural_form: str = None,
        verb_forms: str = None,
        comparative: str = None,
        example_de: str = None,
        example_fa: str = None,
        collocation_de: str = None,
        collocation_fa: str = None,
    ) -> int:
        with self._cursor(commit=True) as c:
            c.execute(
                """
                SELECT id FROM words
                WHERE german = ?
                AND COALESCE(book_id, -1) = ?
                AND COALESCE(lesson_id, -1) = ?
                """,
                (
                    german_word,
                    book_id if book_id is not None else -1,
                    lesson_id if lesson_id is not None else -1,
                ),
            )
            row = c.fetchone()
            if row:
                word_id = row[0]
                c.execute(
                    """
                    UPDATE words SET
                    book_id = ?, lesson_id = ?, article = ?, german = ?, persian = ?,
                    english_meaning = ?, word_type = ?, plural_form = ?, verb_forms = ?, comparative = ?,
                    example_de = ?, example_fa = ?, collocation_de = ?, collocation_fa = ?
                    WHERE id = ?
                    """,
                    (
                        book_id, lesson_id, article, german_word, persian_meaning,
                        english_meaning, word_type, plural_form, verb_forms, comparative,
                        example_de, example_fa, collocation_de, collocation_fa, word_id
                    ),
                )
                return word_id
            try:
                c.execute(
                    """
                    INSERT INTO words (
                    user_id, book_id, lesson_id, article, german, persian,
                    english_meaning, word_type, plural_form, verb_forms, comparative,
                    example_de, example_fa, collocation_de, collocation_fa
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _DEFAULT_OWNER_ID, book_id, lesson_id, article, german_word, persian_meaning,
                        english_meaning, word_type, plural_form, verb_forms, comparative,
                        example_de, example_fa, collocation_de, collocation_fa
                    ),
                )
                return c.lastrowid
            except sqlite3.IntegrityError:
                c.execute(
                """
                SELECT id FROM words
                WHERE german = ?
                  AND COALESCE(book_id, -1) = ?
                  AND COALESCE(lesson_id, -1) = ?
                """,
                (
                    german_word,
                    book_id if book_id is not None else -1,
                    lesson_id if lesson_id is not None else -1,
                ),
            )
                row2 = c.fetchone()
                if not row2:
                    raise
                word_id = row2[0]
                c.execute(
                    """
                    UPDATE words SET
                    book_id = ?, lesson_id = ?, article = ?, german = ?, persian = ?,
                    english_meaning = ?, word_type = ?, plural_form = ?, verb_forms = ?, comparative = ?,
                    example_de = ?, example_fa = ?, collocation_de = ?, collocation_fa = ?
                    WHERE id = ?
                    """,
                    (
                        book_id, lesson_id, article, german_word, persian_meaning,
                        english_meaning, word_type, plural_form, verb_forms, comparative,
                        example_de, example_fa, collocation_de, collocation_fa, word_id
                    ),
                )
                return word_id

    def get_word_by_id(self, word_id: int) -> Optional[Word]:
        with self._cursor() as c:
            c.execute(f"SELECT {self._word_columns()} FROM words WHERE id = ?", (word_id,))
            row = c.fetchone()
            return self._row_to_word(row) if row else None

    def get_word_objects_by_ids(self, word_ids: List[int]) -> List[Word]:
        if not word_ids:
            return []

        placeholders = ",".join("?" for _ in word_ids)
        with self._cursor() as c:
            c.execute(
                f"SELECT {self._word_columns()} FROM words WHERE id IN ({placeholders})",
                tuple(word_ids),
            )
            rows = c.fetchall()

        by_id = {row[0]: self._row_to_word(row) for row in rows}
        return [by_id[wid] for wid in word_ids if wid in by_id]

    def get_all_word_objects(self) -> List[Word]:
        with self._cursor() as c:
            c.execute(f"SELECT {self._word_columns()} FROM words ORDER BY german")
            return [self._row_to_word(row) for row in c.fetchall()]

    def get_words_by_type(
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

        with self._cursor() as c:
            c.execute(query, tuple(params))
            return [self._row_to_word(row) for row in c.fetchall()]

    def get_words_by_lesson_full(self, lesson_id: int) -> List[Dict]:
        with self._cursor() as c:
            c.execute(
                """
                SELECT id, article, german, persian, word_type,
                plural_form, verb_forms, comparative, example_de, example_fa,
                english_meaning, collocation_de, collocation_fa
                FROM words
                WHERE lesson_id = ?
                ORDER BY word_type, german
                """,
                (lesson_id,),
            )
            rows = c.fetchall()
            result = []
            for r in rows:
                result.append({
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
                })
            return result
    def get_words_without_collocation(self, limit: int = 200) -> List[Dict]:
        with self._cursor() as c:
            c.execute(
                """SELECT id, german, persian, article, word_type FROM words
                   WHERE (collocation_de IS NULL OR collocation_de = '')
                   ORDER BY id LIMIT ?""",
                (limit,),
            )
            return [
                {"id": r[0], "german": r[1], "persian": r[2],
                 "article": r[3], "word_type": r[4]}
                for r in c.fetchall()
            ]

    def update_collocation(self, word_id: int, collocation_de: str, collocation_fa: str):
        with self._cursor(commit=True) as c:
            c.execute(
                "UPDATE words SET collocation_de = ?, collocation_fa = ? WHERE id = ?",
                (collocation_de, collocation_fa, word_id),
            )

    def get_word_count(self) -> int:
        with self._cursor() as c:
            c.execute("SELECT COUNT(*) FROM words")
            return c.fetchone()[0]

    def get_word_count_by_lesson(self, lesson_id: int) -> int:
        with self._cursor() as c:
            c.execute("SELECT COUNT(*) FROM words WHERE lesson_id = ?", (lesson_id,))
            return c.fetchone()[0]

    def get_random_word_object(
        self,
        lesson_id: int = None,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> Optional[Word]:
        query = f"SELECT {self._word_columns()} FROM words WHERE 1=1"
        params = []

        if lesson_id:
            query += " AND lesson_id = ?"
            params.append(lesson_id)

        exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "id")
        query += exclude_sql
        query += " ORDER BY RANDOM() LIMIT 1"
        params.extend(exclude_params)

        with self._cursor() as c:
            c.execute(query, tuple(params))
            row = c.fetchone()
            return self._row_to_word(row) if row else None

    def get_nouns_with_article_objects(
        self,
        lesson_id: int = None,
        limit: int = 100,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
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

        with self._cursor() as c:
            c.execute(query, tuple(params))
            return [self._row_to_word(row) for row in c.fetchall()]

    def get_words_with_example_objects(
        self,
        lesson_id: int = None,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
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

        with self._cursor() as c:
            c.execute(query, tuple(params))
            return [self._row_to_word(row) for row in c.fetchall()]

    def get_new_word_objects(
        self,
        user_id: int,
        lesson_id: int = None,
        limit: int = 20,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
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

        with self._cursor() as c:
            c.execute(query, tuple(params))
            return [self._row_to_word(row) for row in c.fetchall()]

    # SRS / Review

    def get_due_word_objects(
        self,
        user_id: int,
        limit: int = 20,
        lesson_id: int = None,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        query = f"""
            SELECT {self._word_columns('w')}
            FROM words w
            JOIN word_stats ws ON w.id = ws.word_id
            WHERE ws.user_id = ?
              AND date(ws.next_review) <= date('now')
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

        with self._cursor() as c:
            c.execute(query, tuple(params))
            return [self._row_to_word(row) for row in c.fetchall()]

    def get_weak_word_objects(
        self,
        user_id: int,
        limit: int = 20,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
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

        with self._cursor() as c:
            c.execute(query, tuple(params))
            return [self._row_to_word(row) for row in c.fetchall()]


    def get_weak_words_by_lesson(
        self,
        user_id: int,
        lesson_id: int,
        limit: int = 10,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        """کلماتی از یک درس خاص که wrong_count > correct_count دارند."""
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

        with self._cursor() as c:
            c.execute(query, tuple(params))
            return [self._row_to_word(row) for row in c.fetchall()]
    def get_flashcard_words(
        self,
        user_id: int,
        limit: int = 10,
        lesson_id: int = None,
        include_new: bool = True,
        new_limit: int = 5,
        exclude_ids: Optional[Iterable[int]] = None,
    ) -> List[Word]:
        exclude_ids = set(exclude_ids or [])

        due_words = self.get_due_word_objects(
            user_id=user_id,
            limit=limit,
            lesson_id=lesson_id,
            exclude_ids=exclude_ids,
        )

        result = list(due_words)
        exclude_ids.update(w.id for w in result)

        if include_new and len(result) < limit:
            remaining_new = min(new_limit, limit - len(result))
            if remaining_new > 0:
                query = f"""
                    SELECT {self._word_columns('w')}
                    FROM words w
                    LEFT JOIN word_stats ws ON ws.word_id = w.id AND ws.user_id = ?
                    WHERE ws.word_id IS NULL
                """
                params = [user_id]

                if lesson_id:
                    query += " AND w.lesson_id = ?"
                    params.append(lesson_id)

                exclude_sql, exclude_params = self._not_in_clause(exclude_ids, "w.id")
                query += exclude_sql
                query += " ORDER BY RANDOM() LIMIT ?"
                params.extend(exclude_params)
                params.append(remaining_new)

                with self._cursor() as c:
                    c.execute(query, tuple(params))
                    result.extend(self._row_to_word(row) for row in c.fetchall())

        return result

    def get_words_due_today(self, user_id: int) -> List[Tuple]:
        with self._cursor() as c:
            c.execute(
                """
                SELECT w.id, w.german, w.persian
                FROM words w
                JOIN word_stats ws ON w.id = ws.word_id
                WHERE ws.user_id = ?
                  AND date(ws.next_review) <= date('now')
                ORDER BY ws.next_review ASC
                """,
                (user_id,),
            )
            return c.fetchall()

    def get_due_word_count(self, user_id: int) -> int:
        with self._cursor() as c:
            c.execute(
                """
                SELECT COUNT(*)
                FROM words w
                JOIN word_stats ws ON w.id = ws.word_id
                WHERE ws.user_id = ?
                  AND date(ws.next_review) <= date('now')
                """,
                (user_id,),
            )
            return c.fetchone()[0]

    def get_weak_word_count(self, user_id: int) -> int:
        with self._cursor() as c:
            c.execute(
                """
                SELECT COUNT(*)
                FROM words w
                JOIN word_stats ws ON w.id = ws.word_id
                WHERE ws.user_id = ?
                  AND ws.wrong_count > ws.correct_count
                """,
                (user_id,),
            )
            return c.fetchone()[0]

    def update_word_stats_fsrs(
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
    ):
        with self._cursor(commit=True) as c:
            c.execute(
                "SELECT correct_count, wrong_count FROM word_stats WHERE user_id = ? AND word_id = ?",
                (user_id, word_id),
            )
            result = c.fetchone()

            if result:
                old_correct, old_wrong = result
                new_correct = old_correct + correct
                new_wrong = old_wrong + wrong

                c.execute(
                    """
                    UPDATE word_stats SET
                        correct_count = ?, wrong_count = ?,
                        ease_factor = ?, interval_days = ?, srs_level = ?,
                        last_reviewed = ?, next_review = ?,
                        phase = ?, stability = ?, difficulty = ?
                    WHERE user_id = ? AND word_id = ?
                    """,
                    (
                        new_correct, new_wrong, ease_factor, interval_days, srs_level,
                        last_review, next_review, phase, stability, difficulty,
                        user_id, word_id
                    ),
                )
            else:
                c.execute(
                    """
                    INSERT INTO word_stats (
                        user_id, word_id, correct_count, wrong_count,
                        ease_factor, interval_days, srs_level, last_reviewed, next_review,
                        phase, stability, difficulty
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, word_id, correct, wrong, ease_factor, interval_days,
                        srs_level, last_review, next_review, phase, stability, difficulty
                    ),
                )

    def get_word_stats_full(self, user_id: int, word_id: int) -> Optional[Dict]:
        with self._cursor() as c:
            c.execute(
                """
                SELECT correct_count, wrong_count, ease_factor, interval_days,
                       next_review, phase, stability, difficulty, srs_level
                FROM word_stats
                WHERE user_id = ? AND word_id = ?
                """,
                (user_id, word_id),
            )
            row = c.fetchone()

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

    def update_quiz_stats(self, user_id: int, is_correct: bool):
        with self._cursor(commit=True) as c:
            c.execute(
                """
                INSERT INTO user_stats (user_id, correct_answers, total_answers)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id) DO UPDATE SET
                    total_answers = total_answers + 1,
                    correct_answers = correct_answers + ?
                """,
                (user_id, 1 if is_correct else 0, 1 if is_correct else 0),
            )

    def get_quiz_stats(self, user_id: int) -> Tuple[int, int]:
        with self._cursor() as c:
            c.execute(
                "SELECT correct_answers, total_answers FROM user_stats WHERE user_id = ?",
                (user_id,),
            )
            result = c.fetchone()
            return result if result else (0, 0)

    def get_user_settings(self, user_id: int) -> Dict:
        with self._cursor() as c:
            c.execute(
                "SELECT preferred_level FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            result = c.fetchone()

        if result:
            return {"preferred_level": result[0] or "A1"}

        return {"preferred_level": "A1"}

    # ---------- Gamification + Same-day review ----------
    def _today_local(self) -> str:
        tz = timezone(timedelta(hours=3, minutes=30))
        return datetime.now(tz).strftime("%Y-%m-%d")

    def get_user_progress(self, user_id: int) -> Dict:
        with self._cursor() as c:
            c.execute(
                "SELECT xp, streak, last_active_date FROM user_progress WHERE user_id=?",
                (user_id,),
            )
            r = c.fetchone()
            if r:
                return {"xp": r[0] or 0, "streak": r[1] or 0, "last_active_date": r[2]}
            return {"xp": 0, "streak": 0, "last_active_date": None}

    def record_activity(self, user_id: int, xp_gain: int) -> Dict:
        today = self._today_local()
        with self._cursor(commit=True) as c:
            c.execute(
                "SELECT xp, streak, last_active_date FROM user_progress WHERE user_id=?",
                (user_id,),
            )
            r = c.fetchone()
            if r is None:
                xp = max(0, xp_gain)
                streak = 1
                c.execute(
                    "INSERT INTO user_progress(user_id, xp, streak, last_active_date) "
                    "VALUES(?,?,?,?)",
                    (user_id, xp, streak, today),
                )
            else:
                xp = (r[0] or 0) + max(0, xp_gain)
                old_streak = r[1] or 0
                last = r[2]
                if last == today:
                    streak = old_streak if old_streak > 0 else 1
                elif last is None:
                    streak = 1
                else:
                    try:
                        gap = (
                            datetime.strptime(today, "%Y-%m-%d")
                            - datetime.strptime(last, "%Y-%m-%d")
                        ).days
                        streak = (old_streak + 1) if gap == 1 else 1
                    except Exception:
                        streak = 1
                c.execute(
                    "UPDATE user_progress SET xp=?, streak=?, last_active_date=? "
                    "WHERE user_id=?",
                    (xp, streak, today, user_id),
                )
            return {"xp": xp, "streak": streak}

    @staticmethod
    def level_from_xp(xp: int):
        level = (xp // 100) + 1
        return level, xp % 100, 100

    def add_pending_review(self, user_id: int, word_id: int, hours: float = 4.0) -> None:
        due_str = (_utc_now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._cursor(commit=True) as c:
            c.execute(
                "SELECT due_at FROM pending_reviews WHERE user_id=? AND word_id=?",
                (user_id, word_id),
            )
            r = c.fetchone()
            if r is None:
                c.execute(
                    "INSERT INTO pending_reviews(user_id, word_id, due_at) VALUES(?,?,?)",
                    (user_id, word_id, due_str),
                )
            elif r[0] and r[0] > due_str:
                c.execute(
                    "UPDATE pending_reviews SET due_at=? WHERE user_id=? AND word_id=?",
                    (due_str, user_id, word_id),
                )

    def get_pending_review_word_ids(self, user_id: int) -> List[int]:
        with self._cursor() as c:
            c.execute(
                "SELECT word_id FROM pending_reviews "
                "WHERE user_id=? AND due_at <= datetime('now')",
                (user_id,),
            )
            return [r[0] for r in c.fetchall()]

    def count_pending_reviews(self, user_id: int) -> int:
        with self._cursor() as c:
            c.execute(
                "SELECT COUNT(*) FROM pending_reviews "
                "WHERE user_id=? AND due_at <= datetime('now')",
                (user_id,),
            )
            return c.fetchone()[0]

    def clear_pending_reviews(self, user_id: int, word_ids: List[int]) -> None:
        if not word_ids:
            return
        ph = ",".join("?" for _ in word_ids)
        with self._cursor(commit=True) as c:
            c.execute(
                f"DELETE FROM pending_reviews WHERE user_id=? AND word_id IN ({ph})",
                [user_id] + list(word_ids),
            )

    def add_grammar_point(
        self, lesson_id, topic_key, title_fa, level, explanation_fa,
        rule_de, examples_json, exercises_json, certainty, note,
    ):
        with self._cursor(commit=True) as c:
            c.execute(
                "SELECT id FROM grammar_points WHERE lesson_id=? AND topic_key=?",
                (lesson_id, topic_key),
            )
            row = c.fetchone()
            if row:
                gid = row[0]
                c.execute(
                    """UPDATE grammar_points SET title_fa=?, level=?, explanation_fa=?,
                       rule_de=?, examples_json=?, exercises_json=?, certainty=?, note=?
                       WHERE id=?""",
                    (title_fa, level, explanation_fa, rule_de, examples_json,
                     exercises_json, certainty, note, gid),
                )
                return gid
            c.execute(
                """INSERT INTO grammar_points
                   (lesson_id, topic_key, title_fa, level, explanation_fa, rule_de,
                    examples_json, exercises_json, certainty, note)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (lesson_id, topic_key, title_fa, level, explanation_fa, rule_de,
                 examples_json, exercises_json, certainty, note),
            )
            return c.lastrowid

    def get_grammar_points_by_lesson(self, lesson_id):
        with self._cursor() as c:
            c.execute(
                "SELECT id, topic_key, title_fa FROM grammar_points "
                "WHERE lesson_id=? ORDER BY id",
                (lesson_id,),
            )
            return [{"id": r[0], "topic_key": r[1], "title_fa": r[2]} for r in c.fetchall()]

    def get_grammar_point(self, gid):
        with self._cursor() as c:
            c.execute(
                """SELECT id, lesson_id, topic_key, title_fa, level, explanation_fa,
                          rule_de, examples_json, exercises_json, certainty, note
                   FROM grammar_points WHERE id=?""",
                (gid,),
            )
            r = c.fetchone()
            if not r:
                return None
            return {
                "id": r[0], "lesson_id": r[1], "topic_key": r[2], "title_fa": r[3],
                "level": r[4], "explanation_fa": r[5], "rule_de": r[6],
                "examples_json": r[7], "exercises_json": r[8], "certainty": r[9], "note": r[10],
            }

    # ---------- Stories ----------
    def add_story(self, lesson_id, title_de, title_fa, text_de, text_fa,
                  target_word_ids, questions_json, level):
        with self._cursor(commit=True) as c:
            c.execute(
                """INSERT INTO stories
                   (lesson_id, title_de, title_fa, text_de, text_fa,
                    target_word_ids, questions_json, level)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (lesson_id, title_de, title_fa, text_de, text_fa,
                 target_word_ids, questions_json, level),
            )
            return c.lastrowid

    def get_stories_by_lesson(self, lesson_id):
        with self._cursor() as c:
            c.execute(
                """SELECT id, title_de, title_fa, text_de, text_fa,
                          target_word_ids, questions_json, level
                   FROM stories WHERE lesson_id = ? ORDER BY id""",
                (lesson_id,),
            )
            return [
                {"id": r[0], "title_de": r[1], "title_fa": r[2],
                 "text_de": r[3], "text_fa": r[4], "target_word_ids": r[5],
                 "questions_json": r[6], "level": r[7]}
                for r in c.fetchall()
            ]

    def get_story(self, story_id):
        with self._cursor() as c:
            c.execute(
                """SELECT id, lesson_id, title_de, title_fa, text_de, text_fa,
                          target_word_ids, questions_json, level
                   FROM stories WHERE id = ?""",
                (story_id,),
            )
            r = c.fetchone()
            if not r:
                return None
            return {"id": r[0], "lesson_id": r[1], "title_de": r[2],
                    "title_fa": r[3], "text_de": r[4], "text_fa": r[5],
                    "target_word_ids": r[6], "questions_json": r[7],
                    "level": r[8]}

    def get_story_count_by_lesson(self, lesson_id):
        with self._cursor() as c:
            c.execute(
                "SELECT COUNT(*) FROM stories WHERE lesson_id = ?",
                (lesson_id,),
            )
            return c.fetchone()[0]

    def backup(self, backup_dir: str = "backups") -> str:
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = _utc_now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"words_{timestamp}.db")

        dest = sqlite3.connect(backup_path)
        try:
            self.conn.backup(dest)
        finally:
            dest.close()

        return backup_path

    def close(self):
        try:
            self.conn.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error("Error closing database: %s", e)