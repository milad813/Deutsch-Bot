"""Typed session-state registry.

Single source of truth for every ``context.user_data`` key the bot uses.
Features declare their keys once; ``reset_session()`` iterates the registry
instead of a hand-maintained key list, and per-feature clearing becomes
possible without prefix-matching guesswork.

``services.SESSION_KEYS`` / ``services.reset_session`` are re-exports of this
module so existing call sites keep working.
"""

import logging
from dataclasses import dataclass
from typing import Dict, FrozenSet, Tuple

logger = logging.getLogger(__name__)

# Dynamic key prefixes that are always cleared on session reset
# (awaiting_* input-mode flags, session_* legacy keys).
DYNAMIC_PREFIXES: Tuple[str, ...] = ("awaiting_", "session_")

# Not part of the registry on purpose: holds a live telegram Job instance
# that must be cancelled (not just popped).
TTS_JOB_KEY = "tts_delete_job"


@dataclass(frozen=True)
class SessionFeature:
    """All user_data keys owned by one conversational feature."""

    name: str
    keys: Tuple[str, ...]


SESSION_FEATURES: Dict[str, SessionFeature] = {
    feature.name: feature
    for feature in (
        SessionFeature(
            "llm_chat",
            ("conversation_history",),
        ),
        SessionFeature(
            "quiz",
            (
                "current_quiz",
                "quiz_session",  # legacy dict-based session
                "quiz_session_obj",
                "quiz_type",
                "quiz_lesson_id",
                "quiz_source_filter",
                "quiz_lesson_preset",
                "quiz_question_sent_at",
                "quiz_flash",
                "quiz_wrong_word_ids",
                "quiz_fixed_word_ids",
                "quiz_answer_lock",
            ),
        ),
        SessionFeature(
            "flashcard",
            (
                "current_flashcard",
                "flashcard_queue",
                "learning_session",  # legacy key
                "active_lesson_id",
                "flashcard_only_new",
                "flashcard_only_due",
                "flashcard_hard_only",
                "flashcard_skipped_ids",
                "flashcard_again_counts",
                "fsrs_guide_shown",
                "flashcard_rate_lock",
                "flashcard_flip_lock",
                "flashcard_skip_lock",
            ),
        ),
        SessionFeature(
            "ltr",
            (
                "ltr_user_id",
                "ltr_words",
                "ltr_lesson_id",
                "ltr_word_results",
                "ltr_current_word_id",
                "ltr_delayed_tasks",
                "ltr_learn_index",
                "ltr_phase",
                "ltr_word_retry_count",
                "ltr_words_learned",
                "ltr_words_tested",
                "ltr_words_passed",
                "ltr_words_failed",
                "ltr_current_question",
                "ltr_current_options",
                "ltr_current_correct_index",
                "ltr_current_correct_text",
                "ltr_question_type",
                "ltr_weak_word_ids",
                "ltr_answer_lock",
                "ltr_learned_lock",
            ),
        ),
        SessionFeature(
            "listening",
            (
                "listening_session",
                "listening_current",
                "listening_answer_lock",
                "listening_skip_lock",
            ),
        ),
        SessionFeature(
            "grammar",
            (
                "grammar_current",
                "grammar_answer_lock",
            ),
        ),
        SessionFeature(
            "story",
            (
                "current_story_id",
                "story_quiz",
                "story_session_word_ids",
                "story_genre_history",
                "story_hint_level",
                "story_answer_lock",
                "story_generating",
                "story_active_job_name",
            ),
        ),
        SessionFeature(
            "tts",
            (
                "tts_message",
                "current_tts_text",
            ),
        ),
    )
}


def all_session_keys() -> FrozenSet[str]:
    """Every static session key registered by any feature."""
    return frozenset(
        key for feature in SESSION_FEATURES.values() for key in feature.keys
    )


# Flat set kept for cheap membership checks and backward compatibility.
SESSION_KEYS: FrozenSet[str] = all_session_keys()


def _cancel_tts_job(context) -> None:
    old_job = context.user_data.pop(TTS_JOB_KEY, None)
    if old_job:
        try:
            old_job.schedule_removal()
        except Exception as e:  # job may already be gone
            logger.debug("Could not cancel stale TTS job: %s", e)


def reset_feature(context, feature_name: str) -> None:
    """Clear only one feature's keys (locks included)."""
    feature = SESSION_FEATURES.get(feature_name)
    if not feature:
        logger.warning("Unknown session feature: %s", feature_name)
        return
    for key in feature.keys:
        context.user_data.pop(key, None)


def reset_session(context) -> None:
    """Clear all transient conversation state for the current user."""
    _cancel_tts_job(context)

    for key in SESSION_KEYS:
        context.user_data.pop(key, None)

    user_data = context.user_data
    for key in list(user_data.keys()):
        if key.startswith(DYNAMIC_PREFIXES):
            user_data.pop(key, None)


def is_session_key(key: str) -> bool:
    """True if the key belongs to the managed session state."""
    return key in SESSION_KEYS or key.startswith(DYNAMIC_PREFIXES)

