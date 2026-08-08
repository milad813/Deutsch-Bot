"""Learning handlers - wrapper for modularized learning module."""

from handlers.learning import (
    FlashcardSessionManager,
    start_flashcard_session,
    handle_next_flashcard,
    handle_flip_card,
    handle_rate_card,
    handle_skip_flashcard,
)
from handlers.learning.ltr_session import LTRSessionManager

# Wrapper functions for backward compatibility
async def handle_ltr_start(query, context):
    """Start LTR session."""
    from handlers.menus import show_ltr_intro
    lesson_id = context.user_data.get('ltr_lesson_id')
    if lesson_id:
        await show_ltr_intro(query, context, lesson_id)

async def handle_ltr_ready(query, context):
    """Handle LTR ready button."""
    from handlers.learning.ltr_session import LTRSessionManager
    ltr_manager = LTRSessionManager(context)
    word = ltr_manager.get_current_word()
    if word:
        from handlers.menus import show_ltr_question
        await show_ltr_question(query, context, word)

async def handle_ltr_summary(query, context):
    """Show LTR session summary."""
    from handlers.menus import show_ltr_session_summary
    await show_ltr_session_summary(query, context)

async def handle_ltr_exit(query, context):
    """Exit LTR session."""
    from handlers.menus import show_main_menu
    context.user_data.pop('ltr_words', None)
    context.user_data.pop('ltr_main_index', None)
    await show_main_menu(query, context)

async def handle_ltr_answer(query, context, suffix):
    """Handle LTR answer selection."""
    try:
        word_id = int(suffix)
        from handlers.learning.ltr_session import LTRSessionManager
        ltr_manager = LTRSessionManager(context)
        word = ltr_manager.get_word_by_id(word_id)
        if word:
            from handlers.menus import handle_ltr_answer_result
            await handle_ltr_answer_result(query, context, word)
    except (ValueError, TypeError):
        pass

async def start_study_session(update, context, lesson_id=None):
    """Start study session for a lesson."""
    from handlers.menus import show_study_session
    if lesson_id:
        await show_study_session(update, context, lesson_id)

__all__ = [
    'FlashcardSessionManager',
    'LTRSessionManager', 
    'start_flashcard_session',
    'handle_next_flashcard',
    'handle_flip_card',
    'handle_rate_card',
    'handle_skip_flashcard',
    'handle_ltr_start',
    'handle_ltr_ready',
    'handle_ltr_summary',
    'handle_ltr_exit',
    'handle_ltr_answer',
    'start_study_session',
]
