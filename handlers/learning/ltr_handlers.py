"""LTR (Learn-Test-Review) handlers - Refactored with multiple question types.

Flow:
1. Learn: Show word MINIMALLY → user can reveal details → confirms "learned"
2. After DELAY_AFTER_LEARN words, trigger Test
3. Test: Random question type (meaning/reverse/cloze/article)
4. If wrong → schedule retry with contextual feedback
5. When all words learned & tested → Summary with breakdown
"""

import logging
import random
import re
from typing import Optional
from handlers.learning.ltr_session import MAX_RETRIES

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# بعد:
# قبل:
from handlers.learning.ltr_session import LTRSessionManager, _ltr_answer_keyboard
from models import Word
from option_generator import get_wrong_options, make_options
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
    MAX_LTR_WORDS = 10  # حداکثر کلمات یک session LTR

    weak_words = db.words.get_weak_by_lesson(user_id, lesson_id, limit=MAX_LTR_WORDS)
    remaining = MAX_LTR_WORDS - len(weak_words)
    new_words = []
    if remaining > 0:
        new_words = db.words.get_new_word_objects(
            user_id, lesson_id=lesson_id, limit=remaining
        )
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

    # Show intro message
    total = len(weak_words) + len(new_words)
    intro_msg = (
        f"🧠 <b>تمرین عمیق (LTR)</b>\n"
        f"📚 {total} کلمه برای یادگیری\n\n"
        f"روش کار:\n"
        f"۱. 📖 کلمه را یاد می‌گیری\n"
        f"۲. ❓ بعد از چند کلمه، ازت سوال می‌پرسم\n"
        f"۳. 🔁 اگه اشتباه زدی، دوباره می‌پرسم\n\n"
        f"بریم شروع کنیم! 👇"
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 شروع!", callback_data="ltr_ready")],
            [InlineKeyboardButton("🏁 انصراف", callback_data="ltr_exit")],
        ]
    )
    await render(query, intro_msg, reply_markup=kb)


# ═══════════════════════════════════════════════════════════════════
# LEARN Phase - Minimal UI
# ═══════════════════════════════════════════════════════════════════


async def _show_learn_word(query, context):
    """Show a word MINIMALLY for the user to learn."""
    ltr = LTRSessionManager(context)
    word = ltr.get_next_word_to_learn()

    # ✅ Guard: prevent infinite recursion
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

    # ─── MINIMAL UI: Only essential info ───
    parts = [
        f"📚 <b>کلمه {progress.get('learned', 0) + 1} از {progress.get('total', 0)}</b>",
        f"{progress.get('progress_bar', '')} ({progress.get('percentage', 0)}%)",
        "",
    ]

    # Word type emoji
    type_emoji = _get_word_type_emoji(word.word_type)

    # Core info: German + Persian
    if word.article:
        parts.append(f"{type_emoji} <b>{esc(word.article)} {esc(word.german)}</b>")
    else:
        parts.append(f"{type_emoji} <b>{esc(word.german)}</b>")

    parts.append(f"🇮🇷 {esc(word.persian)}")

    # English meaning (optional, brief)
    # English meaning (optional, brief)
    if word.english_meaning:
        parts.append(f"🇬🇧 <i>{esc(word.english_meaning)}</i>")

    # ✅ NEW: Extra forms (plural, verb forms, comparative)
    if word.extra_forms_line:
        parts.append(f"📖 {esc(word.extra_forms_line)}")

    # نمایش مثال در صفحه learn
    if word.example_de:
        parts.append("")
        parts.append(f"📝 {esc(word.example_de)}")
        if word.example_fa:
            parts.append(f"   🇮🇷 <i>{esc(word.example_fa)}</i>")

    if word.collocation_line:
        parts.append(f"🔗 {esc(word.collocation_line)}")

    # ─── Keyboard ───

    from handlers.learning.ltr_session import _ltr_learn_keyboard

    await render(
        query, "\n".join(parts), reply_markup=_ltr_learn_keyboard(word_id=word.id)
    )


async def handle_ltr_learned(query, context):
    """User confirms they learned the word."""
    # ✅ Lock: جلوگیری از double-tap
    lock_key = "ltr_learned_lock"
    if context.user_data.get(lock_key):
        try:
            await query.answer()
        except Exception:
            pass
        return
    context.user_data[lock_key] = True

    try:
        ltr = LTRSessionManager(context)
        word = ltr.get_next_word_to_learn()

        if not word:
            await _route_next_action(query, context)
            return

        # Mark as learned and schedule delayed test
        ltr.mark_word_learned(word.id)

        # Route to next action (learn more or test)
        await _route_next_action(query, context)
    finally:
        context.user_data.pop(lock_key, None)


# ═══════════════════════════════════════════════════════════════════
# TEST Phase - Multiple Question Types
# ═══════════════════════════════════════════════════════════════════


async def _show_test_question(query, context, word_id: int):
    """Show a quiz question with RANDOM question type."""
    word = db.words.get_by_id(word_id)
    if not word:
        await _route_next_action(query, context)
        return

    # Set current question
    context.user_data["ltr_current_question"] = word_id
    context.user_data["current_tts_text"] = word.display_german

    # ─── Select question type ───
    q_type = _select_question_type(word)
    context.user_data["ltr_question_type"] = q_type

    # ─── Generate question based on type ───
    if q_type == "article":
        await _render_article_question(query, context, word)
    elif q_type == "cloze":
        await _render_cloze_question(query, context, word)
    elif q_type == "reverse":
        await _render_reverse_question(query, context, word)
    else:  # "meaning" (default)
        await _render_meaning_question(query, context, word)


def _select_question_type(word: Word) -> str:
    """Select appropriate question type based on word properties."""
    types = ["meaning", "reverse"]

    # Add article question for nouns
    if word.word_type == "Noun" and word.article:
        types.append("article")

    # Add cloze question if example exists
    if word.example_de and word.german:
        types.append("cloze")

    return random.choice(types)


async def _render_meaning_question(query, context, word: Word):
    """Question: Show German → Choose Persian meaning."""
    correct_answer = word.persian

    # Get wrong Persian options
    wrong_options = get_wrong_options(
        db, word, count=3, attr_getter=lambda w: w.persian
    )
    options = make_options(correct_answer, wrong_options, total=4, min_options=2)
    if not options or len(options) < 2 or correct_answer not in options:
        # Fallback to reverse
        await _render_reverse_question(query, context, word)
        return

    # Store for validation
    context.user_data["ltr_current_options"] = options
    context.user_data["ltr_current_correct_index"] = options.index(correct_answer)
    context.user_data["ltr_current_correct_text"] = correct_answer

    msg = f"🧠 <b>معنی این کلمه چیست؟</b>\n\n" f"🇩🇪 <b>{esc(word.display_german)}</b>"

    await render(query, msg, reply_markup=_ltr_answer_keyboard(options))


async def _render_reverse_question(query, context, word: Word):
    """Question: Show Persian → Choose German word."""
    correct_answer = word.display_german

    wrong_options = get_wrong_options(
        db, word, count=3, attr_getter=lambda w: w.display_german
    )
    options = make_options(correct_answer, wrong_options, total=4, min_options=2)
    if not options or len(options) < 2 or correct_answer not in options:
        await _render_meaning_question(query, context, word)
        return

    context.user_data["ltr_current_options"] = options
    context.user_data["ltr_current_correct_index"] = options.index(correct_answer)
    context.user_data["ltr_current_correct_text"] = correct_answer

    msg = (
        f"🔄 <b>معادل آلمانی این کلمه کدام است؟</b>\n\n"
        f"🇮🇷 <b>{esc(word.persian)}</b>"
    )

    await render(query, msg, reply_markup=_ltr_answer_keyboard(options))


async def _render_cloze_question(query, context, word: Word):
    """Question: Show sentence with blank → Choose correct word."""
    sentence = word.example_de or ""
    if not sentence:
        await _render_meaning_question(query, context, word)
        return

    # Try to find and blank out the word
    pattern = re.compile(rf"\b({re.escape(word.german)}[a-zäöüß]*)\b", re.IGNORECASE)
    match = pattern.search(sentence)

    if not match:
        # Try without article
        if word.article:
            full_word = f"{word.article} {word.german}"
            pattern = re.compile(
                rf"\b({re.escape(full_word)}[a-zäöüß]*)\b", re.IGNORECASE
            )
            match = pattern.search(sentence)

    if not match:
        await _render_meaning_question(query, context, word)
        return

    # Create sentence with blank
    blanked = sentence[: match.start()] + "______" + sentence[match.end() :]
    correct_answer = match.group(1)

    wrong_options = get_wrong_options(
        db, word, count=3, attr_getter=lambda w: w.display_german
    )
    options = make_options(correct_answer, wrong_options, total=4, min_options=2)
    if not options or len(options) < 2 or correct_answer not in options:
        await _render_meaning_question(query, context, word)
        return

    context.user_data["ltr_current_options"] = options
    context.user_data["ltr_current_correct_index"] = options.index(correct_answer)
    context.user_data["ltr_current_correct_text"] = correct_answer

    msg = (
        f"📝 <b>جای خالی را پر کنید:</b>\n\n"
        f"🇩🇪 {esc(blanked)}\n"
        f"🇮🇷 <i>{esc(word.persian)}</i>"
    )

    await render(query, msg, reply_markup=_ltr_answer_keyboard(options))


async def _render_article_question(query, context, word: Word):
    """Question: Show noun without article → Choose der/die/das."""
    if not word.article or word.word_type != "Noun":
        await _render_meaning_question(query, context, word)
        return

    correct_answer = word.article.lower()
    all_articles = ["der", "die", "das"]
    options = all_articles  # Always 3 options for article

    context.user_data["ltr_current_options"] = options
    context.user_data["ltr_current_correct_index"] = options.index(correct_answer)
    context.user_data["ltr_current_correct_text"] = correct_answer

    msg = (
        f"🎯 <b>آرتیکل صحیح این کلمه چیست؟</b>\n\n"
        f"🇩🇪 ______ <b>{esc(word.german)}</b>\n"
        f"🇮🇷 {esc(word.persian)}"
    )

    await render(query, msg, reply_markup=_ltr_answer_keyboard(options))


# ═══════════════════════════════════════════════════════════════════
# Answer Handling
# ═══════════════════════════════════════════════════════════════════


async def handle_ltr_answer(query, context, suffix: str):
    """Handle user's answer to LTR quiz question."""
    lock_key = "ltr_answer_lock"

    if context.user_data.get(lock_key):
        try:
            await query.answer()
        except Exception:
            pass
        return

    context.user_data[lock_key] = True

    try:
        try:
            option_index = int(suffix)
        except (ValueError, TypeError):
            try:
                await query.answer("⚠️ گزینه نامعتبر.", show_alert=True)
            except Exception:
                pass
            return

        ltr = LTRSessionManager(context)

        word_id = context.user_data.get("ltr_current_question")

        if not word_id:
            await render(
                query, "⚠️ سوالی فعال نیست.", reply_markup=back_inline_keyboard()
            )
            return

        options = context.user_data.get("ltr_current_options", [])
        correct_index = context.user_data.get("ltr_current_correct_index", -1)
        correct_text = context.user_data.get("ltr_current_correct_text", "")
        q_type = context.user_data.get("ltr_question_type", "meaning")

        if option_index < 0 or option_index >= len(options):
            try:
                await query.answer("⚠️ گزینه نامعتبر.", show_alert=True)
            except Exception:
                pass
            return

        is_correct = option_index == correct_index

        word = db.words.get_by_id(word_id)

        # Record result
        ltr.record_test_result(word_id, is_correct)

        # Record skill
        user_id = query.from_user.id
        db.learning.record_skill(user_id, word_id, "ltr", is_correct)

        if not is_correct:
            db.learning.record_mistake(
                user_id=user_id,
                word_id=word_id,
                skill_type="ltr",
                quiz_type=q_type,
                user_answer=(
                    options[option_index] if option_index < len(options) else None
                ),
                correct_answer=correct_text,
            )

        # ─── Feedback with context ───
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
            feedback = f"❌ اشتباه بود.\n✅ جواب درست: <b>{esc(correct_text)}</b>"

        # Add contextual hint
        if word and word.example_de:
            feedback += f"\n📝 <i>{esc(word.example_de)}</i>"

        if word and word.collocation_line:
            feedback += f"\n🔗 {esc(word.collocation_line)}"

        # Clean current question state
        context.user_data.pop("ltr_current_options", None)
        context.user_data.pop("ltr_current_correct_index", None)
        context.user_data.pop("ltr_current_correct_text", None)
        context.user_data.pop("ltr_question_type", None)

        # Check retry info
        retry_count = ltr.user_data.get("ltr_word_retry_count", {}).get(word_id, 0)

        if not is_correct and retry_count > 0:
            feedback += f"\n⚠️ تلاش {retry_count} از {MAX_RETRIES}"

        # Route to next action
        await _route_next_action(query, context, feedback=feedback)

    finally:
        context.user_data.pop(lock_key, None)


# ═══════════════════════════════════════════════════════════════════
# Router
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
        task = tasks.pop(0)
        await _show_test_question(query, context, task["word_id"])
        return

    # 4. Done!
    await _show_ltr_summary(query, context, feedback=feedback)


# ═══════════════════════════════════════════════════════════════════
# Summary & Exit
# ═══════════════════════════════════════════════════════════════════


async def _show_ltr_summary(query, context, feedback: str = ""):
    """Show final session summary with detailed breakdown."""
    ltr = LTRSessionManager(context)

    # Finalize all words (update SRS)
    ltr.finalize_all_passed_words()

    summary = ltr.get_session_summary()

    parts = []
    if feedback:
        parts.append(feedback)
        parts.append("")

    parts.extend(
        [
            "📊 <b>خلاصه جلسه تمرین عمیق (LTR)</b>",
            "",
            f"📚 کل کلمات: {summary['total_words']}",
            f"✅ قبول: {summary['passed_words']}",
            f"❌ نیاز به مرور: {summary['failed_words']}",
            f"🎯 دقت: {summary['accuracy']}%",
        ]
    )

    # Show failed words if any
    if summary["failed_words"] > 0 and summary.get("failed_ids"):
        parts.append("")
        parts.append("📌 <b>کلماتی که نیاز به مرور دارند:</b>")
        for wid in summary["failed_ids"][:5]:
            w = db.words.get_by_id(wid)
            if w:
                parts.append(f"  • {esc(w.display_german)} = {esc(w.persian)}")
        if summary["failed_words"] > 5:
            parts.append(f"  ... و {summary['failed_words'] - 5} کلمه دیگر")

    parts.append("")
    if summary["accuracy"] >= 80:
        parts.append("🎉 عالی! تسلط خوبی داری!")
    elif summary["accuracy"] >= 60:
        parts.append("👍 خوبه! ادامه بده!")
    else:
        parts.append("💡 پیشنهاد: فلش‌کارت این درس را مرور کن.")

    # Clear session
    ltr.clear_session()

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎴 فلش‌کارت مرور", callback_data="flashcard_due")],
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
        ]
    )
    await render(query, "\n".join(parts), reply_markup=kb)


async def handle_ltr_summary(query, context):
    """External summary handler."""
    await _show_ltr_summary(query, context)


async def handle_ltr_exit(query, context):
    """Exit LTR session, but finalize already-tested words."""
    ltr = LTRSessionManager(context)

    try:
        ltr.finalize_partial_session()
    except Exception as e:
        logger.warning("خطا در finalize کردن LTR هنگام خروج: %s", e)

    ltr.clear_session()

    kb = InlineKeyboardMarkup(
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    )

    await render(query, "❌ جلسه تمرین عمیق لغو شد.", reply_markup=kb)


# ═══════════════════════════════════════════════════════════════════
# Legacy compatibility
# ═══════════════════════════════════════════════════════════════════


async def handle_ltr_ready(query, context):
    """Legacy: redirect to learn flow."""
    await _show_learn_word(query, context)


# ═══════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════


def _get_word_type_emoji(word_type: Optional[str]) -> str:
    """Get emoji for word type."""
    emojis = {
        "Noun": "🏷️",
        "Verb": "🏃",
        "Adjective": "🎨",
        "Adverb": "➡️",
        "Preposition": "📍",
        "Pronoun": "👤",
        "Conjunction": "🔗",
        "Phrase": "💬",
    }
    return emojis.get(word_type, "📌")


__all__ = [
    "handle_study_lesson",
    "handle_ltr_learned",
    "handle_ltr_answer",
    "handle_ltr_summary",
    "handle_ltr_exit",
    "handle_ltr_ready",
]
