"""Tests for core/sessions.py — the typed session-state registry."""

from types import SimpleNamespace

from core.sessions import (
    SESSION_FEATURES,
    SESSION_KEYS,
    all_session_keys,
    is_session_key,
    reset_feature,
    reset_session,
)

# The legacy hand-maintained list from services.py (Phase-0 state).
LEGACY_SESSION_KEYS = {
    "conversation_history", "current_quiz", "quiz_session", "quiz_session_obj",
    "quiz_type", "quiz_lesson_id", "quiz_source_filter", "quiz_lesson_preset",
    "quiz_question_sent_at", "current_flashcard", "flashcard_queue",
    "learning_session", "active_lesson_id", "quiz_flash", "quiz_wrong_word_ids",
    "quiz_fixed_word_ids", "current_tts_text", "flashcard_only_new",
    "flashcard_only_due", "flashcard_hard_only", "flashcard_skipped_ids",
    "flashcard_again_counts", "tts_message", "ltr_words", "ltr_lesson_id",
    "ltr_word_results", "ltr_current_word_id", "ltr_delayed_tasks",
    "ltr_learn_index", "ltr_phase", "ltr_word_retry_count", "ltr_words_learned",
    "ltr_words_tested", "ltr_words_passed", "ltr_words_failed",
    "ltr_current_question", "fsrs_guide_shown", "grammar_current",
    "current_story_id", "story_quiz", "ltr_user_id", "story_session_word_ids",
    "story_genre_history", "story_hint_level", "ltr_current_options",
    "ltr_current_correct_index", "ltr_current_correct_text", "ltr_question_type",
    "listening_session", "listening_current", "quiz_answer_lock",
    "ltr_answer_lock", "ltr_learned_lock", "flashcard_rate_lock",
    "flashcard_flip_lock", "flashcard_skip_lock", "story_answer_lock",
    "grammar_answer_lock", "listening_answer_lock", "listening_skip_lock",
    "story_generating",
}


def test_registry_covers_every_legacy_key():
    missing = LEGACY_SESSION_KEYS - set(SESSION_KEYS)
    assert not missing, f"registry lost legacy keys: {missing}"


def test_registry_contains_b10_fix_key():
    """ltr_weak_word_ids used to leak across sessions (bug B10)."""
    assert "ltr_weak_word_ids" in SESSION_KEYS
    assert "ltr_weak_word_ids" in set(SESSION_FEATURES["ltr"].keys)


def test_registry_keys_have_no_duplicates_across_features():
    seen = {}
    for name, feature in SESSION_FEATURES.items():
        for key in feature.keys:
            assert key not in seen, f"{key} owned by both {seen[key]} and {name}"
            seen[key] = name


class _FakeUserData(dict):
    def pop(self, key, default=None):
        return super().pop(key, default) if key in self else default


def _context():
    return SimpleNamespace(user_data=_FakeUserData())


def test_reset_session_clears_keys_prefixes_and_tts_job():
    ctx = _context()
    job = SimpleNamespace(schedule_removal=lambda: None)
    ctx.user_data.update(
        {
            "tts_delete_job": job,
            "quiz_answer_lock": True,
            "ltr_words": [1, 2],
            "awaiting_story_genre": True,
            "session_legacy": 1,
            "keep_me": "untouched",  # unknown keys survive (persistence data)
        }
    )

    reset_session(ctx)

    assert "quiz_answer_lock" not in ctx.user_data
    assert "ltr_words" not in ctx.user_data
    assert "awaiting_story_genre" not in ctx.user_data
    assert "session_legacy" not in ctx.user_data
    assert ctx.user_data["keep_me"] == "untouched"


def test_reset_feature_is_scoped():
    ctx = _context()
    ctx.user_data.update({"grammar_current": {"a": 1}, "quiz_type": "meaning"})

    reset_feature(ctx, "grammar")

    assert "grammar_current" not in ctx.user_data
    assert ctx.user_data["quiz_type"] == "meaning"


def test_is_session_key():
    assert is_session_key("quiz_answer_lock")
    assert is_session_key("awaiting_x")
    assert not is_session_key("random_user_setting")
