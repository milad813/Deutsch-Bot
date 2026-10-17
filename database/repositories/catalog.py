"""Books, lessons, stories and grammar content."""

from typing import Dict, List, Optional
import sqlite3
from database.connection import DatabaseConnection
from database.repositories.base import BaseRepository


class BookRepository(BaseRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def create(self, name: str, level: str = "A1") -> int:
        try:
            return self.insert("INSERT INTO books (name, level) VALUES (?, ?)", (name, level))
        except sqlite3.IntegrityError:
            row = self.fetch_one("SELECT id FROM books WHERE name = ?", (name,))
            return row[0] if row else 0

    def get_all(self) -> list:
        return self.fetch_all("SELECT id, name, level FROM books ORDER BY name")

    def get_by_id(self, book_id: int) -> tuple:
        return self.fetch_one("SELECT id, name, level FROM books WHERE id = ?", (book_id,))

    def get_level_by_lesson(self, lesson_id: int) -> Optional[str]:
        row = self.fetch_one(
            """SELECT b.level FROM books b JOIN lessons l ON b.id = l.book_id WHERE l.id = ?""",
            (lesson_id,),
        )
        return row[0] if row else None

    def get_count(self) -> int:
        """Return the total number of books in the catalogue.

        Used by the admin ``/status`` view. Returns 0 for an empty or
        missing table so the admin page never crashes mid-render.
        """
        import sqlite3

        try:
            row = self.fetch_one("SELECT COUNT(*) FROM books")
        except sqlite3.OperationalError:
            return 0
        return row[0] if row else 0


class LessonRepository(BaseRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def create(self, book_id: int, lesson_number: int, title: str = None) -> int:
        try:
            return self.insert(
                "INSERT INTO lessons (book_id, lesson_number, title) VALUES (?, ?, ?)",
                (book_id, lesson_number, title),
            )
        except sqlite3.IntegrityError:
            row = self.fetch_one(
                "SELECT id FROM lessons WHERE book_id = ? AND lesson_number = ?",
                (book_id, lesson_number),
            )
            return row[0] if row else 0

    def get_by_book(self, book_id: int) -> list:
        return self.fetch_all(
            "SELECT id, lesson_number, title FROM lessons WHERE book_id = ? ORDER BY lesson_number",
            (book_id,),
        )

    def get_by_id(self, lesson_id: int) -> tuple:
        return self.fetch_one(
            "SELECT id, lesson_number, title FROM lessons WHERE id = ?", (lesson_id,)
        )

    def get_book_id(self, lesson_id: int) -> Optional[int]:
        row = self.fetch_one("SELECT book_id FROM lessons WHERE id = ?", (lesson_id,))
        return row[0] if row else None

    def update_title(self, lesson_id: int, title: str) -> None:
        self.execute(
            "UPDATE lessons SET title = ? WHERE id = ? AND (title IS NULL OR title = '')",
            (title, lesson_id),
            commit=True,
        )

    def get_count(self) -> int:
        """Return the total number of lessons in the catalogue.

        Used by the admin ``/status`` view. Returns 0 for an empty or
        missing table so the admin page never crashes mid-render.
        """
        import sqlite3

        try:
            row = self.fetch_one("SELECT COUNT(*) FROM lessons")
        except sqlite3.OperationalError:
            return 0
        return row[0] if row else 0


class StoryRepository(BaseRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def add(
        self,
        lesson_id,
        title_de,
        title_fa,
        text_de,
        text_fa,
        target_word_ids=None,
        questions_json=None,
        level=None,
    ) -> int:
        return self.insert(
            """INSERT INTO stories (lesson_id, title_de, title_fa, text_de, text_fa,
                            target_word_ids, questions_json, level) VALUES (?,?,?,?,?,?,?,?)""",
            (
                lesson_id,
                title_de,
                title_fa,
                text_de,
                text_fa,
                target_word_ids,
                questions_json,
                level,
            ),
        )

    def get_by_lesson(self, lesson_id: int) -> list:
        return self.fetch_all(
            """SELECT id, lesson_id, title_de, title_fa, text_de, text_fa,
                                 target_word_ids, questions_json, level, created_at
                                 FROM stories WHERE lesson_id = ? ORDER BY id""",
            (lesson_id,),
        )

    def get_by_id(self, story_id: int) -> Optional[Dict]:
        row = self.fetch_one(
            """SELECT id, lesson_id, title_de, title_fa, text_de, text_fa,
                                target_word_ids, questions_json, level FROM stories WHERE id = ?""",
            (story_id,),
        )
        if not row:
            return None
        return {
            "id": row[0],
            "lesson_id": row[1],
            "title_de": row[2],
            "title_fa": row[3],
            "text_de": row[4],
            "text_fa": row[5],
            "target_word_ids": row[6],
            "questions_json": row[7],
            "level": row[8],
        }

    def get_count(self, lesson_id: int) -> int:
        row = self.fetch_one("SELECT COUNT(*) FROM stories WHERE lesson_id = ?", (lesson_id,))
        return row[0] if row else 0


class GrammarRepository(BaseRepository):
    def __init__(self, connection: DatabaseConnection):
        super().__init__(connection)

    def upsert(
        self,
        lesson_id,
        topic_key,
        title_fa,
        level,
        explanation_fa,
        rule_de,
        examples_json,
        exercises_json,
        certainty,
        note,
    ) -> int:
        row = self.fetch_one(
            "SELECT id FROM grammar_points WHERE lesson_id=? AND topic_key=?",
            (lesson_id, topic_key),
        )
        if row:
            gid = row[0]
            self.execute(
                """UPDATE grammar_points SET title_fa=?, level=?, explanation_fa=?, rule_de=?,
                            examples_json=?, exercises_json=?, certainty=?, note=? WHERE id=?""",
                (
                    title_fa,
                    level,
                    explanation_fa,
                    rule_de,
                    examples_json,
                    exercises_json,
                    certainty,
                    note,
                    gid,
                ),
                commit=True,
            )
            return gid
        return self.insert(
            """INSERT INTO grammar_points (lesson_id, topic_key, title_fa, level, explanation_fa,
                            rule_de, examples_json, exercises_json, certainty, note)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                lesson_id,
                topic_key,
                title_fa,
                level,
                explanation_fa,
                rule_de,
                examples_json,
                exercises_json,
                certainty,
                note,
            ),
        )

    def get_by_lesson(self, lesson_id) -> List[Dict]:
        rows = self.fetch_all(
            "SELECT id, topic_key, title_fa FROM grammar_points WHERE lesson_id=? ORDER BY id",
            (lesson_id,),
        )
        return [{"id": r[0], "topic_key": r[1], "title_fa": r[2]} for r in rows]

    def get_by_id(self, gid) -> Optional[Dict]:
        r = self.fetch_one(
            """SELECT id, lesson_id, topic_key, title_fa, level, explanation_fa,
                              rule_de, examples_json, exercises_json, certainty, note
                              FROM grammar_points WHERE id=?""",
            (gid,),
        )
        if not r:
            return None
        return {
            "id": r[0],
            "lesson_id": r[1],
            "topic_key": r[2],
            "title_fa": r[3],
            "level": r[4],
            "explanation_fa": r[5],
            "rule_de": r[6],
            "examples_json": r[7],
            "exercises_json": r[8],
            "certainty": r[9],
            "note": r[10],
        }
