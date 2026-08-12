"""LTR (Learn-Test-Review) handlers - CORRECT implementation.

Flow:
1. Learn: Show word with details → user confirms "learned"
2. After DELAY_AFTER_LEARN words, trigger Test
3. Test: Quiz question about a previously learned word
4. If wrong → schedule retry
5. When all words learned & tested → Summary
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.learning.ltr_session import (
    LTRSessionManager,
    _ltr_answer_keyboard,
    _ltr_learn_keyboard,
    _ltr_wrong_display_german_options,
    _make_ltr_options,
)
from services import db
from ui import back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════

async def handle_study_lesson(query, context, suffix: str):
    """Start LTR session for a lesson."""
    try:
        lesson_id = int(suffix)
    except ValueError:
        return

    user_id = query.from_user.id
    weak_words = db.get_weak_words_by_lesson(user_id, lesson_id, limit=20)
    new_words = db.get_new_word_objects(user_id, lesson_id=lesson_id, limit=20)

    if not weak_words and not new_words:
        await render(
            query,
            "🎉 هیچ کلمه‌ی جدید یا ضعیفی در این درس ندارید!",
            reply_markup=back_inline_keyboard(),
        )
        return

    ltr = LTRSessionManager(context)
    if not ltr.initialize(user_id, lesson_id, weak_words, new_words):
        await render(query, "❌ خطا در شروع جلسه.", reply_markup=back_inline_keyboard())
        return

    # Show first word to learn
    await _show_learn_word(query, context)


# ═══════════════════════════════════════════════════════════════════
# LEARN Phase
# ═══════════════════════════════════════════════════════════════════

async def _show_learn_word(query, context):
    """Show a word for the user to learn."""
    ltr = LTRSessionManager(context)
    word = ltr.get_next_word_to_learn()

    # ✅ FIX: جلوگیری از حلقه بی‌نهایت (RecursionError)
    # اگر کلمه‌ای برای یادگیری نیست، مستقیم برو سراغ تست یا پایان
    if not word:
        task = ltr.get_due_test()
        if task:
            await _show_test_question(query, context, task["word_id"])
        else:
            await _show_ltr_summary(query, context)
        return

    # Set TTS text
    context.user_data["current_tts_text"] = word.display_german

    progress = ltr.get_progress_info()

    # Build learn message
    parts = [
        f"📚 <b>یادگیری کلمه {progress.get('learned', 0) + 1} از {progress.get('total', 0)}</b>",
        f"{progress.get('progress_bar', '')} ({progress.get('percentage', 0)}%)",
        "",
        f"🇩🇪 <b>{esc(word.display_german)}</b>",
        f"🇮🇷 {esc(word.persian)}",
    ]

    if getattr(word, 'english_meaning', None):
        parts.append(f"🇬🇧 {esc(word.english_meaning)}")

    if getattr(word, 'extra_forms_line', None):
        parts.append(f"📖 {esc(word.extra_forms_line)}")

    if getattr(word, 'example_de', None):
        parts.append(f"📝 {esc(word.example_de)}")
    if getattr(word, 'example_fa', None):
        parts.append(f"🇮🇷 <i>{esc(word.example_fa)}</i>")

    if getattr(word, 'collocation_line', None):
        parts.append(f"🔗 {esc(word.collocation_line)}")

    from handlers.learning.ltr_session import _ltr_learn_keyboard
    await render(query, "\n".join(parts), reply_markup=_ltr_learn_keyboard())

async def handle_ltr_learned(query, context):
    """User confirms they learned the word."""
    ltr = LTRSessionManager(context)
    word = ltr.get_next_word_to_learn()

    if not word:
        await _route_next_action(query, context)
        return

    # Mark as learned and schedule delayed test
    ltr.mark_word_learned(word.id)

    # Route to next action (learn more or test)
    await _route_next_action(query, context)


# ═══════════════════════════════════════════════════════════════════
# TEST  Phase
# ═══════════════════════════════════════════════════════════════════

async def _show_test_question(query, context, word_id: int):
    """Show a quiz question for a previously learned word."""
    word = db.get_word_by_id(word_id)
    if not word:
        await _route_next_action(query, context)
        return

    # Set current question
    context.user_data["ltr_current_question"] = word_id
    context.user_data["current_tts_text"] = word.display_german

    # Generate options
    correct_answer = word.display_german
    wrong_options = _ltr_wrong_display_german_options(word, count=3)
    options = _make_ltr_options(correct_answer, wrong_options, total=4, min_options=2)

    if not options or len(options) < 2 or correct_answer not in options:
        # Can't generate options, skip this test
        ltr = LTRSessionManager(context)
        ltr.record_test_result(word_id, True)  # Auto-pass
        await _route_next_action(query, context)
        return

    # Store for validation
    context.user_data["ltr_current_options"] = options
    context.user_data["ltr_current_correct_index"] = options.index(correct_answer)
    context.user_data["ltr_current_correct_text"] = correct_answer

    # Check if this is a retry
    ltr = LTRSessionManager(context)
    retry_count = ltr.user_data.get("ltr_word_retry_count", {}).get(word_id, 0)
    retry_label = " 🔁" if retry_count > 0 else ""

    msg = (
        f"🇮🇷 <b>{esc(word.persian)}</b>\n"
        f"معادل آلمانی این کلمه کدام است؟"
    )

    await render(query, msg, reply_markup=_ltr_answer_keyboard(options))


async def handle_ltr_answer(query, context, suffix: str):
    """Handle user's answer to LTR quiz question."""
    try:
        option_index = int(suffix)
    except (ValueError, TypeError):
        return

    ltr = LTRSessionManager(context)
    word_id = context.user_data.get("ltr_current_question")

    if not word_id:
        await render(query, "⚠️ سوالی فعال نیست.", reply_markup=back_inline_keyboard())
        return

    options = context.user_data.get("ltr_current_options", [])
    correct_index = context.user_data.get("ltr_current_correct_index", -1)
    correct_text = context.user_data.get("ltr_current_correct_text", "")

    if option_index < 0 or option_index >= len(options):
        return

    is_correct = option_index == correct_index
    word = db.get_word_by_id(word_id)

    # Record result
    ltr.record_test_result(word_id, is_correct)

    # Record skill
    user_id = query.from_user.id
    db.learning.record_skill(user_id, word_id, "ltr", is_correct)

    if not is_correct:
        db.learning.record_mistake(
            user_id=user_id, word_id=word_id,
            skill_type="ltr", quiz_type="ltr",
            user_answer=options[option_index] if option_index < len(options) else None,
            correct_answer=correct_text,
        )

    # Give feedback
    if is_correct:
        try:
            await query.answer("✅ درست بود!", show_alert=False)
        except Exception:
            pass
        feedback = "✅ آفرین! درست بود!"
    else:
        try:
            await query.answer(f"❌ جواب: {correct_text}", show_alert=True)
        except Exception:
            pass
        feedback = f"❌ اشتباه بود. جواب درست: <b>{esc(correct_text)}</b>"

    # Clean current question state
    context.user_data.pop("ltr_current_options", None)
    context.user_data.pop("ltr_current_correct_index", None)
    context.user_data.pop("ltr_current_correct_text", None)

    # Check if this word needs retry (was scheduled)
    retry_count = ltr.user_data.get("ltr_word_retry_count", {}).get(word_id, 0)
    if not is_correct and retry_count > 0:
        feedback += f"\n⚠️ تلاش {retry_count} از {2}"

    # Route to next action
    await _route_next_action(query, context, feedback=feedback)


# ═══════════════════════════════════════════════════════════════════
# Router - decides what to do next
# ═══════════════════════════════════════════════════════════════════

async def _route_next_action(query, context, feedback: str = ""):
    """Main router: decides whether to learn, test, or finish."""
    ltr = LTRSessionManager(context)

    # 1. Check if there's a due test
    task = ltr.get_due_test()
    if task:
        await _show_test_question(query, context, task["word_id"])
        return

    # 2. Check if there are words left to learn
    word = ltr.get_next_word_to_learn()
    if word:
        await _show_learn_word(query, context)
        return

    # 3. Check if there are pending tests (not yet due but no more to learn)
    tasks = ltr.user_data.get("ltr_delayed_tasks", [])
    if tasks:
        # Force the next test to avoid deadlock
        task = tasks.pop(0)
        await _show_test_question(query, context, task["word_id"])
        return

    # 4. Done!
    await _show_ltr_summary(query, context, feedback=feedback)

# ═══════════════════════════════════════════════════════════════════
# Summary & Exit
# ═══════════════════════════════════════════════════════════════════

async def _show_ltr_summary(query, context, feedback: str = ""):
    """Show final session summary."""
    ltr = LTRSessionManager(context)

    # Finalize all words (update SRS)
    ltr.finalize_all_passed_words()

    summary = ltr.get_session_summary()

    parts = []
    if feedback:
        parts.append(feedback)
        parts.append("")

    parts.extend([
        "📊 <b>خلاصه جلسه تمرین عمیق (LTR)</b>",
        f"📚 کل کلمات: {summary['total_words']}",
        f"✅ قبول: {summary['passed_words']}",
        f"❌ نیاز به مرور: {summary['failed_words']}",
        f"🎯 دقت: {summary['accuracy']}%",
    ])

    if summary["failed_words"] > 0:
        parts.append("")
        parts.append("💡 کلماتی که اشتباه زدی در SRS ثبت شدن و زودتر مرور می‌شن.")

    # Clear session
    ltr.clear_session()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    ])
    await render(query, "\n".join(parts), reply_markup=kb)


async def handle_ltr_summary(query, context):
    """External summary handler."""
    await _show_ltr_summary(query, context)


async def handle_ltr_exit(query, context):
    """Exit LTR session."""
    LTRSessionManager(context).clear_session()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    ])
    await render(query, "❌ جلسه تمرین عمیق لغو شد.", reply_markup=kb)


# ═══════════════════════════════════════════════════════════════════
# Legacy compatibility (for callback_router)
# ═══════════════════════════════════════════════════════════════════

async def handle_ltr_ready(query, context):
    """Legacy: redirect to learn flow."""
    await _show_learn_word(query, context)


__all__ = [
    "handle_study_lesson",
    "handle_ltr_learned",
    "handle_ltr_answer",
    "handle_ltr_summary",
    "handle_ltr_exit",
    "handle_ltr_ready",
]