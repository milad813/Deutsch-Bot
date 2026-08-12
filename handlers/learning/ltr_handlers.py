"""LTR (Learn-Test-Review) callback handlers."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from handlers.learning.ltr_session import (
    LTRSessionManager, _ltr_answer_keyboard,
    _ltr_wrong_display_german_options, _make_ltr_options,
    _ltr_intro_keyboard,
)
from services import db
from ui import back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)


async def handle_study_lesson(query, context, suffix: str):
    """Handle study_lesson: callback - start LTR session."""
    try:
        lesson_id = int(suffix)
    except ValueError:
        return
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
    if word:
        await _show_ltr_intro(query, context, word, lesson_id)


async def _show_ltr_intro(query, context, word, lesson_id: int):
    context.user_data["current_tts_text"] = word.display_german
    msg = (
        f"🧠 <b>تمرین عمیق (LTR)</b>\n"
        f"📚 درس: {lesson_id}\n"
        f"🇩🇪 <b>{esc(word.display_german)}</b>\n"
        f"🇮🇷 {esc(word.persian)}\n"
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
        await render(query, "❌ کلمه‌ای در صف نیست.", reply_markup=back_inline_keyboard())


async def _show_ltr_question(query, context, word, notice: str = ""):
    correct_answer = word.german
    if word.article:
        correct_answer = f"{word.article} {word.german}"
    context.user_data["current_tts_text"] = word.display_german

    wrong_options = _ltr_wrong_display_german_options(word, count=3)
    options = _make_ltr_options(correct_answer, wrong_options, total=4, min_options=2)
    if not options or len(options) < 2 or correct_answer not in options:
        await render(query, "❌ خطا در تولید گزینه‌ها.", reply_markup=back_inline_keyboard())
        return

    context.user_data["ltr_current_options"] = options
    context.user_data["ltr_current_correct_index"] = options.index(correct_answer)
    context.user_data["ltr_current_correct_text"] = correct_answer

    progress = LTRSessionManager(context).get_progress_info()
    parts = []
    if notice:
        parts.append(notice)
    parts.append(f"🧠 <b>سوال {progress['position']} از {progress['total']}</b>")
    parts.append(f"{progress['progress_bar']} ({progress['percentage']}%)")
    parts.append(f"🇮🇷 {esc(word.persian)}")
    parts.append("کدام گزینه آلمانی صحیح است؟")

    await render(query, "\n".join(parts), reply_markup=_ltr_answer_keyboard(options, with_tts=False))


async def handle_ltr_answer(query, context, suffix: str):
    try:
        option_index = int(suffix)
    except (ValueError, TypeError):
        return
    ltr_manager = LTRSessionManager(context)
    word = ltr_manager.get_current_word()
    if not word:
        await render(query, "❌ کلمه‌ای پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    options = context.user_data.get("ltr_current_options", [])
    correct_index = context.user_data.get("ltr_current_correct_index", -1)
    correct_text = context.user_data.get("ltr_current_correct_text", "") or word.display_german
    if option_index < 0 or option_index >= len(options):
        return

    is_correct = option_index == correct_index
    ltr_manager.record_word_result(word.id, is_correct)
    user_id = query.from_user.id
    db.learning.record_skill(user_id, word.id, "ltr", is_correct)
    if not is_correct:
        db.learning.record_mistake(
            user_id=user_id, word_id=word.id, skill_type="ltr", quiz_type="ltr",
            user_answer=options[option_index] if option_index < len(options) else None,
            correct_answer=correct_text,
        )

    if is_correct:
        try: await query.answer("✅ درست بود!", show_alert=False)
        except Exception: pass
        feedback = "✅ درست بود!"
    else:
        try: await query.answer(f"❌ جواب درست: {correct_text}", show_alert=True)
        except Exception: pass
        feedback = f"❌ اشتباه بود. جواب درست: <b>{esc(correct_text)}</b>"

    context.user_data.pop("ltr_current_options", None)
    context.user_data.pop("ltr_current_correct_index", None)
    context.user_data.pop("ltr_current_correct_text", None)
    await _show_ltr_result_and_continue(query, context, word, is_correct, feedback)


async def _show_ltr_result_and_continue(query, context, word, is_correct, feedback: str = ""):
    ltr_manager = LTRSessionManager(context)
    ltr_manager.finalize_word(word.id, user_id=query.from_user.id)
    if ltr_manager.advance_to_next_word():
        next_word = ltr_manager.get_current_word()
        if next_word:
            await _show_ltr_question(query, context, next_word, notice=feedback)
            return
    await handle_ltr_summary(query, context)


async def handle_ltr_summary(query, context):
    ltr_manager = LTRSessionManager(context)
    summary = ltr_manager.get_session_summary()
    msg = (
        f"📊 <b>خلاصه جلسه تمرین عمیق</b>\n"
        f"✅ کلمات صحیح: {summary['correct_words']} از {summary['total_words']}\n"
        f"❌ کلمات غلط: {summary['wrong_words']}\n"
        f"🎯 دقت: {summary['accuracy']}%\n"
    )
    if summary["wrong_word_ids"]:
        msg += "⚠️ کلماتی که نیاز به مرور بیشتر دارند ثبت شدند.\n"
    ltr_manager.clear_session()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]])
    await render(query, msg, reply_markup=kb)


async def handle_ltr_exit(query, context):
    LTRSessionManager(context).clear_session()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]])
    await render(query, "❌ جلسه تمرین عمیق لغو شد.", reply_markup=kb)


__all__ = [
    "handle_study_lesson", "handle_ltr_ready", "handle_ltr_summary",
    "handle_ltr_exit", "handle_ltr_answer",
]