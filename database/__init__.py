"""Database package with repository pattern for data access."""

from database.connection import DEFAULT_OWNER_ID, DatabaseConnection, _utc_now
from database.repositories import (
    BookRepository,
    ExtendedWordRepository,
    GrammarRepository,
    LearningRepository,
    LessonRepository,
    StoryRepository,
    UserRepository,
)


class Database:
    def __init__(self, db_name: str = "words.db"):
        self._conn = DatabaseConnection(db_name)
        self.words = ExtendedWordRepository(self._conn)
        self.books = BookRepository(self._conn)
        self.lessons = LessonRepository(self._conn)
        self.users = UserRepository(self._conn)
        self.stories = StoryRepository(self._conn)
        self.grammar = GrammarRepository(self._conn)
        self.learning = LearningRepository(self._conn)
        self._ensure_learning_schema()

    @property
    def conn(self):
        return self._conn.conn

    def close(self):
        self._conn.close()

    def backup(self, backup_dir: str = "backups") -> str:
        return self._conn.backup(backup_dir)

    @staticmethod
    def level_from_xp(xp: int) -> tuple:
        level = (xp // 100) + 1
        current = xp % 100
        needed = 100
        return level, current, needed

    def _ensure_learning_schema(self):
        for migration_sql in (
        "ALTER TABLE word_skills ADD COLUMN correct_streak INTEGER DEFAULT 0",
        "ALTER TABLE grammar_progress ADD COLUMN correct_streak INTEGER DEFAULT 0",
        "ALTER TABLE story_progress ADD COLUMN next_review TIMESTAMP",  # ← جدید
    ):
            try:
                c.execute(migration_sql)
            except Exception:
                pass
        with self._conn.cursor(commit=True) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS word_skills (
                user_id INTEGER NOT NULL, word_id INTEGER NOT NULL,
                skill_type TEXT NOT NULL, correct_count INTEGER DEFAULT 0,
                wrong_count INTEGER DEFAULT 0, last_reviewed TIMESTAMP,
                last_wrong_at TIMESTAMP,
                PRIMARY KEY (user_id, word_id, skill_type))""")
            c.execute("""CREATE TABLE IF NOT EXISTS mistakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                word_id INTEGER, grammar_point_id INTEGER, story_id INTEGER,
                skill_type TEXT, quiz_type TEXT, user_answer TEXT,
                correct_answer TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            c.execute("""CREATE TABLE IF NOT EXISTS mistake_stats (
                user_id INTEGER NOT NULL, word_id INTEGER NOT NULL,
                skill_type TEXT NOT NULL, wrong_count INTEGER DEFAULT 0,
                last_wrong_at TIMESTAMP, resolved_at TIMESTAMP,
                PRIMARY KEY (user_id, word_id, skill_type))""")
            c.execute("""CREATE TABLE IF NOT EXISTS grammar_progress (
                user_id INTEGER NOT NULL, grammar_point_id INTEGER NOT NULL,
                correct_count INTEGER DEFAULT 0, wrong_count INTEGER DEFAULT 0,
                last_reviewed TIMESTAMP, next_review TIMESTAMP,
                PRIMARY KEY (user_id, grammar_point_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS story_progress (
                user_id INTEGER NOT NULL, story_id INTEGER NOT NULL,
                correct_count INTEGER DEFAULT 0, wrong_count INTEGER DEFAULT 0,
                last_reviewed TIMESTAMP, PRIMARY KEY (user_id, story_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS llm_examples (
                word_id INTEGER NOT NULL, level TEXT NOT NULL, example_de TEXT,
                example_fa TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(word_id, level))""")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_word_skills_user_word ON word_skills(user_id, word_id)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_mistakes_user ON mistakes(user_id, created_at)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_mistake_stats_user ON mistake_stats(user_id, last_wrong_at)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_grammar_progress_user ON grammar_progress(user_id, next_review)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_story_progress_user ON story_progress(user_id, story_id)"
            )
            for migration_sql in (
                "ALTER TABLE word_skills ADD COLUMN correct_streak INTEGER DEFAULT 0",
            ):
                try:
                    c.execute(migration_sql)
                except Exception:
                    pass


__all__ = ["Database", "DatabaseConnection", "_utc_now", "DEFAULT_OWNER_ID"]
