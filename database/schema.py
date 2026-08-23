"""Schema definition for the Deutsch-Bot database.

Extracted from database/__init__.py so the DDL lives in one reviewable
place, separate from the Database facade.

Conventions:
- Tables use CREATE TABLE IF NOT EXISTS (idempotent bootstrap).
- Older databases are upgraded via safe *additive* migrations:
  each ``ALTER TABLE ... ADD COLUMN`` is attempted and duplicate-column
  errors are ignored.
- Bump SCHEMA_VERSION whenever adding tables/columns here.
"""

SCHEMA_VERSION = 1

# ─────────────────────────────────────────────────────────────────────
# Tables
# ─────────────────────────────────────────────────────────────────────

TABLE_STATEMENTS = (
    # Core tables
    """
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        level TEXT DEFAULT 'A1',
        UNIQUE(name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id INTEGER,
        lesson_number INTEGER,
        title TEXT,
        UNIQUE(book_id, lesson_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_active_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_stats (
        user_id INTEGER PRIMARY KEY,
        correct_answers INTEGER DEFAULT 0,
        total_answers INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_progress (
        user_id INTEGER PRIMARY KEY,
        xp INTEGER DEFAULT 0,
        streak INTEGER DEFAULT 0,
        last_active_date TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER PRIMARY KEY,
        preferred_level TEXT DEFAULT 'A1',
        daily_goal INTEGER DEFAULT 10
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER DEFAULT 1,
        book_id INTEGER,
        lesson_id INTEGER,
        article TEXT,
        german TEXT NOT NULL,
        persian TEXT,
        english_meaning TEXT,
        word_type TEXT,
        plural_form TEXT,
        verb_forms TEXT,
        comparative TEXT,
        example_de TEXT,
        example_fa TEXT,
        collocation_de TEXT,
        collocation_fa TEXT,
        cefr_estimated TEXT,
        topics TEXT,
        contexts TEXT,
        common_situations TEXT,
        story_roles TEXT,
        related_words TEXT,
        common_collocations_de TEXT,
        story_suitability INTEGER DEFAULT 3,
        story_suitability_reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS word_stats (
        user_id INTEGER NOT NULL,
        word_id INTEGER NOT NULL,
        correct_count INTEGER DEFAULT 0,
        wrong_count INTEGER DEFAULT 0,
        ease_factor REAL DEFAULT 2.5,
        interval_days REAL DEFAULT 0,
        srs_level INTEGER DEFAULT 0,
        last_reviewed TIMESTAMP,
        next_review TIMESTAMP,
        phase TEXT DEFAULT 'new',
        stability REAL DEFAULT 0,
        difficulty REAL DEFAULT 0,
        PRIMARY KEY (user_id, word_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lesson_id INTEGER,
        title_de TEXT,
        title_fa TEXT,
        text_de TEXT,
        text_fa TEXT,
        target_word_ids TEXT,
        questions_json TEXT,
        level TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grammar_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lesson_id INTEGER,
        topic_key TEXT,
        title_fa TEXT,
        level TEXT,
        explanation_fa TEXT,
        rule_de TEXT,
        examples_json TEXT,
        exercises_json TEXT,
        certainty TEXT,
        note TEXT,
        UNIQUE(lesson_id, topic_key)
    )
    """,
    # Learning tables
    """
    CREATE TABLE IF NOT EXISTS word_skills (
        user_id INTEGER NOT NULL,
        word_id INTEGER NOT NULL,
        skill_type TEXT NOT NULL,
        correct_count INTEGER DEFAULT 0,
        wrong_count INTEGER DEFAULT 0,
        last_reviewed TIMESTAMP,
        last_wrong_at TIMESTAMP,
        correct_streak INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, word_id, skill_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mistakes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        word_id INTEGER,
        grammar_point_id INTEGER,
        story_id INTEGER,
        skill_type TEXT,
        quiz_type TEXT,
        user_answer TEXT,
        correct_answer TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mistake_stats (
        user_id INTEGER NOT NULL,
        word_id INTEGER NOT NULL,
        skill_type TEXT NOT NULL,
        wrong_count INTEGER DEFAULT 0,
        last_wrong_at TIMESTAMP,
        resolved_at TIMESTAMP,
        PRIMARY KEY (user_id, word_id, skill_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grammar_progress (
        user_id INTEGER NOT NULL,
        grammar_point_id INTEGER NOT NULL,
        correct_count INTEGER DEFAULT 0,
        wrong_count INTEGER DEFAULT 0,
        last_reviewed TIMESTAMP,
        next_review TIMESTAMP,
        correct_streak INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, grammar_point_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS story_progress (
        user_id INTEGER NOT NULL,
        story_id INTEGER NOT NULL,
        correct_count INTEGER DEFAULT 0,
        wrong_count INTEGER DEFAULT 0,
        last_reviewed TIMESTAMP,
        next_review TIMESTAMP,
        PRIMARY KEY (user_id, story_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_examples (
        word_id INTEGER NOT NULL,
        level TEXT NOT NULL,
        example_de TEXT,
        example_fa TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(word_id, level)
    )
    """,
)

# ─────────────────────────────────────────────────────────────────────
# Indexes
# ─────────────────────────────────────────────────────────────────────

INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_books_name ON books(name)",
    "CREATE INDEX IF NOT EXISTS idx_lessons_book ON lessons(book_id)",
    "CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active_at)",
    "CREATE INDEX IF NOT EXISTS idx_words_book ON words(book_id)",
    "CREATE INDEX IF NOT EXISTS idx_words_lesson ON words(lesson_id)",
    "CREATE INDEX IF NOT EXISTS idx_words_german ON words(german)",
    "CREATE INDEX IF NOT EXISTS idx_words_word_type ON words(word_type)",
    "CREATE INDEX IF NOT EXISTS idx_words_cefr ON words(cefr_estimated)",
    "CREATE INDEX IF NOT EXISTS idx_word_stats_user_next ON word_stats(user_id, next_review)",
    "CREATE INDEX IF NOT EXISTS idx_word_stats_user_wrong ON word_stats(user_id, wrong_count)",
    "CREATE INDEX IF NOT EXISTS idx_stories_lesson ON stories(lesson_id)",
    "CREATE INDEX IF NOT EXISTS idx_grammar_points_lesson ON grammar_points(lesson_id)",
    "CREATE INDEX IF NOT EXISTS idx_word_skills_user_word ON word_skills(user_id, word_id)",
    "CREATE INDEX IF NOT EXISTS idx_mistakes_user ON mistakes(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_mistake_stats_user ON mistake_stats(user_id, last_wrong_at)",
    "CREATE INDEX IF NOT EXISTS idx_mistake_stats_unresolved ON mistake_stats(user_id, resolved_at)",
    "CREATE INDEX IF NOT EXISTS idx_grammar_progress_user ON grammar_progress(user_id, next_review)",
    "CREATE INDEX IF NOT EXISTS idx_story_progress_user ON story_progress(user_id, story_id)",
)

# ─────────────────────────────────────────────────────────────────────
# Safe additive migrations (for databases created by older versions)
# ─────────────────────────────────────────────────────────────────────

MIGRATION_STATEMENTS = (
    # books
    "ALTER TABLE books ADD COLUMN level TEXT DEFAULT 'A1'",
    # lessons
    "ALTER TABLE lessons ADD COLUMN book_id INTEGER",
    "ALTER TABLE lessons ADD COLUMN lesson_number INTEGER",
    "ALTER TABLE lessons ADD COLUMN title TEXT",
    # users
    "ALTER TABLE users ADD COLUMN username TEXT",
    "ALTER TABLE users ADD COLUMN first_name TEXT",
    "ALTER TABLE users ADD COLUMN last_name TEXT",
    "ALTER TABLE users ADD COLUMN joined_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN last_active_at TIMESTAMP",
    # user_settings
    "ALTER TABLE user_settings ADD COLUMN preferred_level TEXT DEFAULT 'A1'",
    "ALTER TABLE user_settings ADD COLUMN daily_goal INTEGER DEFAULT 10",
    # words base
    "ALTER TABLE words ADD COLUMN user_id INTEGER DEFAULT 1",
    "ALTER TABLE words ADD COLUMN book_id INTEGER",
    "ALTER TABLE words ADD COLUMN lesson_id INTEGER",
    "ALTER TABLE words ADD COLUMN article TEXT",
    "ALTER TABLE words ADD COLUMN german TEXT",
    "ALTER TABLE words ADD COLUMN persian TEXT",
    "ALTER TABLE words ADD COLUMN english_meaning TEXT",
    "ALTER TABLE words ADD COLUMN word_type TEXT",
    "ALTER TABLE words ADD COLUMN plural_form TEXT",
    "ALTER TABLE words ADD COLUMN verb_forms TEXT",
    "ALTER TABLE words ADD COLUMN comparative TEXT",
    "ALTER TABLE words ADD COLUMN example_de TEXT",
    "ALTER TABLE words ADD COLUMN example_fa TEXT",
    "ALTER TABLE words ADD COLUMN collocation_de TEXT",
    "ALTER TABLE words ADD COLUMN collocation_fa TEXT",
    "ALTER TABLE words ADD COLUMN created_at TIMESTAMP",
    # words new metadata
    "ALTER TABLE words ADD COLUMN cefr_estimated TEXT",
    "ALTER TABLE words ADD COLUMN topics TEXT",
    "ALTER TABLE words ADD COLUMN contexts TEXT",
    "ALTER TABLE words ADD COLUMN common_situations TEXT",
    "ALTER TABLE words ADD COLUMN story_roles TEXT",
    "ALTER TABLE words ADD COLUMN related_words TEXT",
    "ALTER TABLE words ADD COLUMN common_collocations_de TEXT",
    "ALTER TABLE words ADD COLUMN story_suitability INTEGER DEFAULT 3",
    "ALTER TABLE words ADD COLUMN story_suitability_reason TEXT",
    # word_stats
    "ALTER TABLE word_stats ADD COLUMN correct_count INTEGER DEFAULT 0",
    "ALTER TABLE word_stats ADD COLUMN wrong_count INTEGER DEFAULT 0",
    "ALTER TABLE word_stats ADD COLUMN ease_factor REAL DEFAULT 2.5",
    "ALTER TABLE word_stats ADD COLUMN interval_days REAL DEFAULT 0",
    "ALTER TABLE word_stats ADD COLUMN srs_level INTEGER DEFAULT 0",
    "ALTER TABLE word_stats ADD COLUMN last_reviewed TIMESTAMP",
    "ALTER TABLE word_stats ADD COLUMN next_review TIMESTAMP",
    "ALTER TABLE word_stats ADD COLUMN phase TEXT DEFAULT 'review'",
    "ALTER TABLE word_stats ADD COLUMN stability REAL DEFAULT 0",
    "ALTER TABLE word_stats ADD COLUMN difficulty REAL DEFAULT 0",
    # grammar_points
    "ALTER TABLE grammar_points ADD COLUMN lesson_id INTEGER",
    "ALTER TABLE grammar_points ADD COLUMN topic_key TEXT",
    "ALTER TABLE grammar_points ADD COLUMN title_fa TEXT",
    "ALTER TABLE grammar_points ADD COLUMN level TEXT",
    "ALTER TABLE grammar_points ADD COLUMN explanation_fa TEXT",
    "ALTER TABLE grammar_points ADD COLUMN rule_de TEXT",
    "ALTER TABLE grammar_points ADD COLUMN examples_json TEXT",
    "ALTER TABLE grammar_points ADD COLUMN exercises_json TEXT",
    "ALTER TABLE grammar_points ADD COLUMN certainty TEXT",
    "ALTER TABLE grammar_points ADD COLUMN note TEXT",
    # stories
    "ALTER TABLE stories ADD COLUMN lesson_id INTEGER",
    "ALTER TABLE stories ADD COLUMN title_de TEXT",
    "ALTER TABLE stories ADD COLUMN title_fa TEXT",
    "ALTER TABLE stories ADD COLUMN text_de TEXT",
    "ALTER TABLE stories ADD COLUMN text_fa TEXT",
    "ALTER TABLE stories ADD COLUMN target_word_ids TEXT",
    "ALTER TABLE stories ADD COLUMN questions_json TEXT",
    "ALTER TABLE stories ADD COLUMN level TEXT",
    "ALTER TABLE stories ADD COLUMN created_at TIMESTAMP",
    "ALTER TABLE mistakes ADD COLUMN created_at TIMESTAMP",
    "ALTER TABLE llm_examples ADD COLUMN created_at TIMESTAMP",
    # learning tables
    "ALTER TABLE word_skills ADD COLUMN correct_streak INTEGER DEFAULT 0",
    "ALTER TABLE grammar_progress ADD COLUMN correct_streak INTEGER DEFAULT 0",
    "ALTER TABLE story_progress ADD COLUMN next_review TIMESTAMP",
)


def ensure_schema(cursor) -> None:
    """Create tables/indexes and run additive migrations.

    ``cursor`` must be an open sqlite cursor; committing is the caller's
    responsibility (Database passes a commit-on-exit cursor).
    """
    for sql in TABLE_STATEMENTS:
        cursor.execute(sql)

    for sql in INDEX_STATEMENTS:
        try:
            cursor.execute(sql)
        except Exception:
            pass

    for migration_sql in MIGRATION_STATEMENTS:
        try:
            cursor.execute(migration_sql)
        except Exception:
            # Duplicate column errors are expected on existing databases.
            pass