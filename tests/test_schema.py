"""Tests for database/schema.py (extracted DDL)."""

import sqlite3

from database.schema import (
    INDEX_STATEMENTS,
    MIGRATION_STATEMENTS,
    TABLE_STATEMENTS,
    ensure_schema,
)


def _table_names(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


def test_ensure_schema_creates_all_tables():
    conn = sqlite3.connect(":memory:")
    try:
        cur = conn.cursor()
        ensure_schema(cur)
        conn.commit()

        names = _table_names(conn)
        expected = {
            "books",
            "lessons",
            "users",
            "user_stats",
            "user_progress",
            "user_settings",
            "words",
            "word_stats",
            "stories",
            "grammar_points",
            "word_skills",
            "mistakes",
            "mistake_stats",
            "grammar_progress",
            "story_progress",
            "llm_examples",
        }
        missing = expected - names
        assert not missing, f"tables not created: {missing}"
    finally:
        conn.close()


def test_ensure_schema_is_idempotent():
    """Running it twice must not raise (IF NOT EXISTS + ignored ALTERs)."""
    conn = sqlite3.connect(":memory:")
    try:
        cur = conn.cursor()
        ensure_schema(cur)
        conn.commit()
        ensure_schema(cur)
        conn.commit()
    finally:
        conn.close()


def test_statement_counts_unchanged():
    """Guard against accidental schema loss during refactors."""
    assert len(TABLE_STATEMENTS) == 16
    assert len(INDEX_STATEMENTS) == 18
    assert len(MIGRATION_STATEMENTS) == 70
