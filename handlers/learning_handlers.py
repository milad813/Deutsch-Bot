"""Learning handlers - wrapper for modularized learning module."""
import logging
from handlers.learning import (
    FlashcardSessionManager,
    start_flashcard_session,
    handle_next_flashcard,
    handle_flip_card,
    handle_rate_card,
    handle_skip_flashcard,
)
from handlers.learning.ltr_session import (
    LTRSessionManager,
    _ltr_answer_keyboard,
    _ltr_wrong_display_german_options,
    _make_ltr_options,
)
from services import db
from ui import back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)
# Wrapper functions for backward compatibility
async def handle_ltr_start(query, context):
    """Start LTR session - placeholder, actual start is via study_lesson callback."""
    lesson_id = context.user_data.get('ltr_lesson_id')
    if lesson_id:
        await _show_ltr_intro_for_lesson(query, context, lesson_id)

async def _show_ltr_intro_for_lesson(query, context, lesson_id: int):
    user_id = query.from_user.id
    weak_words = db.get_weak_words_by_lesson(user_id, lesson_id, limit=20)
    new_words = db.get_new_word_objects(user_id, lesson_id=lesson_id, limit=20)

    if not weak_words and not new_words:
        await render(query, "🎉 هیچ کلمه‌ی جدید یا ضعیفی در این درس ندارید!",
                     reply_markup=back_inline_keyboard())
        return

    ltr_manager = LTRSessionManager(context)
    if not ltr_manager.initialize(user_id, lesson_id, weak_words, new_words):
        await render(query, "❌ خطا در شروع جلسه.", reply_markup=back_inline_keyboard())
        return

    word = ltr_manager.get_current_word()
    if not word:
        await render(query, "❌ کلمه‌ای پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    from handlers.learning.ltr_session import _ltr_intro_keyboard
    msg = (
        f"🧠 <b>تمرین عمیق (LTR)</b>\n"
        f"🇩🇪 <b>{esc(word.display_german)}</b>\n"
        f"🇮🇷 {esc(word.persian)}\n\n"
        "در این حالت، کلمات را با روش یادگیری فعال تمرین می‌کنیم.\n"
        "برای هر کلمه، چند سوال مختلف پرسیده می‌شود."
    )
    await render(query, msg, reply_markup=_ltr_intro_keyboard())

async def handle_ltr_ready(query, context):
    ltr_manager = LTRSessionManager(context)
    word = ltr_manager.get_current_word()
    if word:
        await _show_ltr_question(query, context, word)
    else:
        await render(query, "❌ کلمه‌ای در صف نیست.",
                     reply_markup=back_inline_keyboard())
        
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
    # ذخیره options برای validate در handle_ltr_answer
    context.user_data["ltr_current_options"] = options
    context.user_data["ltr_current_correct_index"] = options.index(correct_answer)
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
    try:
        option_index = int(suffix)
    except (ValueError, TypeError):
        return

    ltr_manager = LTRSessionManager(context)
    word = ltr_manager.get_current_word()
    if not word:
        await render(query, "❌ کلمه‌ای پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    # ✅ استفاده از options ذخیره‌شده به جای تولید مجدد
    options = context.user_data.get("ltr_current_options", [])
    correct_index = context.user_data.get("ltr_current_correct_index", -1)

    if option_index < 0 or option_index >= len(options):
        return

    is_correct = option_index == correct_index
    ltr_manager.record_word_result(word.id, is_correct)

    # پاک کردن state سوال فعلی
    context.user_data.pop("ltr_current_options", None)
    context.user_data.pop("ltr_current_correct_index", None)

    await _show_ltr_result_and_continue(query, context, word, is_correct)

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
