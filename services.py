from telegram import ReplyKeyboardMarkup

import config
from database import Database
from llm_service import LLMService
from quiz_service import QuizService
from srs_service import FSRSService
from tts_service import TTSService
from ui import main_menu_keyboard

db = Database(config.DB_PATH)
llm = LLMService(db=db)
quiz_service = QuizService()
fsrs = FSRSService(db)
tts = TTSService()

SESSION_KEYS = {
    "conversation_history",
    "current_quiz",
    "quiz_session",
    "quiz_session_obj",
    "quiz_type",
    "quiz_lesson_id",
    "quiz_source_filter",
    "quiz_lesson_preset",
    "current_flashcard",
    "flashcard_queue",
    "learning_session",
    "active_lesson_id",
    "quiz_flash",
    "quiz_wrong_word_ids",
    "quiz_fixed_word_ids",
    "current_tts_text",
    "flashcard_only_new",
    "flashcard_only_due",
    "flashcard_hard_only",
    "flashcard_skipped_ids",
    "flashcard_again_counts",
    "tts_message",
    "study_words",
    "study_index",
    "study_lesson_id",
    "ltr_words",
    "ltr_index",
    "ltr_lesson_id",
    "ltr_word_results",
    "ltr_current_word_id",
    "ltr_state",
    "ltr_correct_answer",
    "ltr_correct_index",
    "ltr_delayed_1",
    "ltr_delayed_2",
    "ltr_round",
    "ltr_main_index",
    "ltr_main_progress",
    "ltr_delayed_tasks",
    "ltr_retry_stage",
    "ltr_current_word_pos",
    "ltr_round2_started",
    "ltr_wrong_in_session",
    "ltr_learn_index",
    "ltr_phase",
    "ltr_word_retry_count",
    "ltr_words_learned",
    "ltr_words_tested",
    "ltr_words_passed",
    "ltr_words_failed",
    "ltr_current_question",
    "fsrs_guide_shown",
    "grammar_current",
    "current_story_id",
    "story_quiz",
    "ltr_user_id",
    "story_session_word_ids",
    "story_genre_history",
    "story_hint_level",
    "ltr_current_options",
    "ltr_current_correct_index",
    "ltr_current_correct_text",
    "ltr_question_type",
    "listening_session",
    "listening_current",
    # Locks / Flags
    "quiz_answer_lock",
    "ltr_answer_lock",
    "ltr_learned_lock",
    "flashcard_rate_lock",
    "flashcard_flip_lock",
    "flashcard_skip_lock",
    "story_answer_lock",
    "grammar_answer_lock",
    "listening_answer_lock",
    "listening_skip_lock",
    "story_generating",
}


def reset_session(context):
    old_job = context.user_data.pop("tts_delete_job", None)
    if old_job:
        try:
            old_job.schedule_removal()
        except Exception:
            pass
    context.user_data.pop("tts_message", None)
    for key in list(context.user_data.keys()):
        if (
            key.startswith("awaiting_")
            or key.startswith("session_")
            or key in SESSION_KEYS
        ):
            context.user_data.pop(key, None)


def get_main_menu_keyboard(
    due_count: int = 0, streak: int = 0, hard_count: int = 0, is_admin: bool = False
) -> ReplyKeyboardMarkup:
    return main_menu_keyboard(due_count, streak, hard_count, is_admin=is_admin)
