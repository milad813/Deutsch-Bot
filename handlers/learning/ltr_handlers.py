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
    """نمایش کلمه اول (فاز Learn) برای شروع جلسه."""
    context.user_data["current_tts_text"] = word.display_german

    msg = (
        f"🧠 <b>تمرین عمیق (LTR)</b>\n"
        f"📚 درس: {lesson_id}\n\n"
        f"🇩🇪 <b>{esc(word.display_german)}</b>\n"
        f"🇮🇷 {esc(word.persian)}\n"
    )
    if word.example_de:
        msg += f"📝 {esc(word.example_de)}\n"
    if word.example_fa:
        msg += f"🇮🇷 <i>{esc(word.example_fa)}</i>\n"

    msg += (
        "\nدر این حالت، هر کلمه را اول <b>یاد می‌گیری</b>، بعد ازت <b>سوال</b> می‌پرسم.\n"
        "🔊 گوش بده و خوب یاد بگیر!"
    )

    await render(query, msg, reply_markup=_ltr_intro_keyboard())


async def handle_ltr_ready(query, context):
    """کاربر آماده است → سوال بپرس."""
    ltr_manager = LTRSessionManager(context)
    word = ltr_manager.get_current_word()
    if word:
        await _show_ltr_question(query, context, word)
    else:
        await render(query, "❌ کلمه‌ای در صف نیست.", reply_markup=back_inline_keyboard())


async def _show_ltr_learn_phase(query, context, word, notice: str = ""):
    """✅ FIX: فاز Learn برای کلمات بعدی (بعد از کلمه اول)."""
    context.user_data["current_tts_text"] = word.display_german

    ltr_manager = LTRSessionManager(context)
    progress = ltr_manager.get_progress_info()

    parts = []
    if notice:
        parts.append(notice)
        parts.append("")  # خط خالی

    parts.append(f"🧠 <b>کلمه {progress['position']} از {progress['total']}</b>")
    parts.append(f"{progress['progress_bar']} ({progress['percentage']}%)")
    parts.append("")
    parts.append(f"🇩🇪 <b>{esc(word.display_german)}</b>")
    parts.append(f"🇮🇷 {esc(word.persian)}")

    if word.example_de:
        parts.append(f"📝 {esc(word.example_de)}")
    if word.example_fa:
        parts.append(f"🇮🇷 <i>{esc(word.example_fa)}</i>")

    if word.extra_forms_line:
        parts.append(f"📖 {esc(word.extra_forms_line)}")

    parts.append("")
    parts.append("👆 خوب یاد بگیر، بعد دکمه «آماده‌ام» را بزن!")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:study")],
        [InlineKeyboardButton("✅ آماده‌ام، سوال بپرس!", callback_data="ltr_ready")],
        [InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")],
    ])

    await render(query, "\n".join(parts), reply_markup=kb)


async def _show_ltr_question(query, context, word, notice: str = ""):
    """نمایش سوال چهارگزینه‌ای."""
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
    parts.append(f"❓ <b>سوال {progress['position']} از {progress['total']}</b>")
    parts.append(f"{progress['progress_bar']} ({progress['percentage']}%)")
    parts.append("")
    parts.append(f"🇮🇷 <b>{esc(word.persian)}</b>")
    parts.append("کدام گزینه آلمانی صحیح است؟")

    await render(query, "\n".join(parts), reply_markup=_ltr_answer_keyboard(options, with_tts=False))


async def handle_ltr_answer(query, context, suffix: str):
    """پردازش جواب کاربر."""
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
        try:
            await query.answer("✅ درست بود!", show_alert=False)
        except Exception:
            pass
        feedback = "✅ درست بود!"
    else:
        try:
            await query.answer(f"❌ جواب درست: {correct_text}", show_alert=True)
        except Exception:
            pass
        feedback = f"❌ اشتباه بود. جواب درست: <b>{esc(correct_text)}</b>"

    # پاک کردن state سوال فعلی
    context.user_data.pop("ltr_current_options", None)
    context.user_data.pop("ltr_current_correct_index", None)
    context.user_data.pop("ltr_current_correct_text", None)

    await _show_ltr_result_and_continue(query, context, word, is_correct, feedback)


async def _show_ltr_result_and_continue(query, context, word, is_correct, feedback: str = ""):
    """نمایش نتیجه و ادامه به کلمه بعدی."""
    ltr_manager = LTRSessionManager(context)
    ltr_manager.finalize_word(word.id, user_id=query.from_user.id)

    if ltr_manager.advance_to_next_word():
        next_word = ltr_manager.get_current_word()
        if next_word:
            # ✅ FIX: به جای رفتن مستقیم به سوال، اول کلمه را یاد بده!
            await _show_ltr_learn_phase(query, context, next_word, notice=feedback)
            return

    await handle_ltr_summary(query, context)


async def handle_ltr_summary(query, context):
    """خلاصه پایان جلسه."""
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

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    ])
    await render(query, msg, reply_markup=kb)


async def handle_ltr_exit(query, context):
    """خروج از جلسه."""
    LTRSessionManager(context).clear_session()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    ])
    await render(query, "❌ جلسه تمرین عمیق لغو شد.", reply_markup=kb)


__all__ = [
    "handle_study_lesson", "handle_ltr_ready", "handle_ltr_summary",
    "handle_ltr_exit", "handle_ltr_answer",
]