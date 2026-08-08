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
    """Start LTR session - placeholder, actual start is via study_lesson callback."""
    lesson_id = context.user_data.get('ltr_lesson_id')
    if lesson_id:
        await _show_ltr_intro_for_lesson(query, context, lesson_id)

async def _show_ltr_intro_for_lesson(query, context, lesson_id: int):
    """Helper to show LTR intro for a lesson (used by handle_ltr_start)."""
    user_id = query.from_user.id
    
    # Get weak and new words for this lesson
    weak_words = db.get_weak_word_objects(user_id, lesson_id=lesson_id, limit=20)
    new_words = db.get_new_word_objects(lesson_id=lesson_id, limit=20)
    
    if not weak_words and not new_words:
        await render(
            query,
            "🎉 هیچ کلمه‌ی جدید یا ضعیفی در این درس ندارید!",
            reply_markup=back_inline_keyboard()
        )
        return
    
    # Initialize LTR session
    ltr_manager = LTRSessionManager(context)
    if not ltr_manager.initialize(user_id, lesson_id, weak_words, new_words):
        await render(
            query,
            "❌ خطا در شروع جلسه.",
            reply_markup=back_inline_keyboard()
        )
        return
    
    # Show intro
    word = ltr_manager.get_current_word()
    if word:
        await _show_ltr_intro(query, context, word, lesson_id)

async def handle_ltr_ready(query, context):
    """Handle LTR ready button - show first question."""
    ltr_manager = LTRSessionManager(context)
    word = ltr_manager.get_current_word()
    if word:
        await _show_ltr_question(query, context, word)

async def _show_ltr_question(query, context, word):
    """Show LTR question for a word."""
    from handlers.learning.ltr_session import (
        _ltr_answer_keyboard,
        _ltr_wrong_display_german_options,
        _make_ltr_options,
    )
    from ui import esc
    
    # Create question: show Persian, ask for German
    correct_answer = word.german
    if word.article:
        correct_answer = f"{word.article} {word.german}"
    
    # Generate wrong options
    wrong_options = _ltr_wrong_display_german_options(word, count=3)
    options = _make_ltr_options(correct_answer, wrong_options, total=4, min_options=2)
    
    if not options:
        await render(
            query,
            "❌ خطا در تولید گزینه‌ها.",
            reply_markup=back_inline_keyboard()
        )
        return
    
    progress = LTRSessionManager(context).get_progress_info()
    
    msg = (
        f"🧠 <b>سوال {progress['position']} از {progress['total']}</b>\\n"
        f"{progress['progress_bar']} ({progress['percentage']}%)\\n\\n"
        f"🇮🇷 {esc(word.persian)}\\n\\n"
        "کدام گزینه آلمانی صحیح است؟"
    )
    
    keyboard = _ltr_answer_keyboard(options, with_tts=False)
    await render(query, msg, reply_markup=keyboard)

async def handle_ltr_summary(query, context):
    """Show LTR session summary."""
    ltr_manager = LTRSessionManager(context)
    summary = ltr_manager.get_session_summary()
    
    msg = (
        f"📊 <b>خلاصه جلسه تمرین عمیق</b>\\n\\n"
        f"✅ کلمات صحیح: {summary['correct_words']} از {summary['total_words']}\\n"
        f"❌ کلمات غلط: {summary['wrong_words']}\\n"
        f"🎯 دقت: {summary['accuracy']}%\\n\\n"
    )
    
    if summary['wrong_word_ids']:
        msg += "⚠️ کلماتی که نیاز به مرور بیشتر دارند ثبت شدند.\\n\\n"
    
    # Clear session
    ltr_manager.clear_session()
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    ])
    
    await render(query, msg, reply_markup=keyboard)

async def handle_ltr_exit(query, context):
    """Exit LTR session."""
    ltr_manager = LTRSessionManager(context)
    ltr_manager.clear_session()
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    ])
    
    await render(query, "❌ جلسه تمرین عمیق لغو شد.", reply_markup=keyboard)

async def handle_ltr_answer(query, context, suffix):
    """Handle LTR answer selection."""
    try:
        option_index = int(suffix)  # suffix is the option index (0,1,2,3), not word_id!
        
        ltr_manager = LTRSessionManager(context)
        word = ltr_manager.get_current_word()
        
        if not word:
            await render(
                query,
                "❌ کلمه‌ای پیدا نشد.",
                reply_markup=back_inline_keyboard()
            )
            return
        
        # Get options from user_data or regenerate
        # For now, we'll just check against the correct answer
        correct_answer = word.german
        if word.article:
            correct_answer = f"{word.article} {word.german}"
        
        # Get the selected option text from callback data
        # We need to extract it from the keyboard - for simplicity, compare index
        wrong_options = _ltr_wrong_display_german_options(word, count=3)
        options = _make_ltr_options(correct_answer, wrong_options, total=4, min_options=2)
        
        if options and option_index < len(options):
            selected_option = options[option_index]
            is_correct = (selected_option == correct_answer)
            
            # Record result
            ltr_manager.record_word_result(word.id, is_correct)
            
            # Show result and move to next
            await _show_ltr_result_and_continue(query, context, word, is_correct)
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Error in handle_ltr_answer: {e}")
        pass

async def _show_ltr_result_and_continue(query, context, word, is_correct):
    """Show result and continue to next word or question."""
    from handlers.learning.ltr_session import _ltr_answer_keyboard, _make_ltr_options, _ltr_wrong_display_german_options
    from ui import esc
    
    ltr_manager = LTRSessionManager(context)
    
    # Finalize this word
    stats = ltr_manager.finalize_word(word.id)
    
    # Move to next word
    has_more = ltr_manager.advance_to_next_word()
    
    if has_more:
        next_word = ltr_manager.get_current_word()
        if next_word:
            await _show_ltr_question(query, context, next_word)
            return
    
    # Session complete - show summary
    await handle_ltr_summary(query, context)

async def start_study_session(update, context, lesson_id=None):
    """Start study session for a lesson - placeholder, actual logic in callback_router."""
    # This function is now handled directly in callback_router._handle_study_lesson
    pass

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
