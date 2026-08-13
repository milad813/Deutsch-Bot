"""Writing practice - user types the German word."""

import logging
import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from learning_engine import record_quiz_answer
from services import db
from ui import back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)


async def start_writing_quiz(query, context, count: int = 5):
    """شروع کوییز نوشتاری."""
    user_id = query.from_user.id
    lesson_id = context.user_data.get("quiz_lesson_id")

    words = db.words.get_due(user_id, limit=count, lesson_id=lesson_id)
    if not words:
        words = db.words.get_new_word_objects(user_id, lesson_id=lesson_id, limit=count)

    if not words:
        await render(
            query, "📭 کلمه‌ای برای تمرین نیست.", reply_markup=back_inline_keyboard()
        )
        return

    random.shuffle(words)
    context.user_data["writing_session"] = {
        "words": [w.id for w in words],
        "current": 0,
        "correct": 0,
        "wrong": 0,
    }

    await _show_writing_question(query, context)


async def _show_writing_question(query, context):
    session = context.user_data.get("writing_session")
    if not session or session["current"] >= len(session["words"]):
        await _show_writing_summary(query, context)
        return

    word_id = session["words"][session["current"]]
    word = db.words.get_by_id(word_id)
    if not word:
        session["current"] += 1
        await _show_writing_question(query, context)
        return

    context.user_data["writing_current_word"] = word_id

    # ✅ راهنمای آرتیکل
    article_hint = ""
    if word.word_type == "Noun" and word.article:
        article_hint = "\n💡 <i>آرتیکل را هم بنویس (der/die/das)</i>"

    msg = (
        f"✍️ <b>تمرین نوشتاری</b> ({session['current']+1}/{len(session['words'])})\n"
        f"🇮🇷 {esc(word.persian)}\n"
        f"معادل آلمانی را تایپ کن:{article_hint}"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏭️ رد شدن", callback_data="writing_skip:")],
            [InlineKeyboardButton("🏁 پایان", callback_data="writing_exit:")],
        ]
    )
    await render(query, msg, reply_markup=kb)
    context.user_data["awaiting_writing_answer"] = True


async def _show_writing_question_from_message(update, context):
    """ادامه سوال بعدی از پیام متنی."""

    class FakeQuery:
        def __init__(self, update):
            self.from_user = update.effective_user
            self.message = update.message
            self.data = ""

        async def answer(self, text=None, show_alert=False):
            pass

    query = FakeQuery(update)
    await _show_writing_question(query, context)


async def _show_writing_summary(query, context):
    session = context.user_data.pop("writing_session", {})
    total = session.get("correct", 0) + session.get("wrong", 0)
    correct = session.get("correct", 0)

    msg = (
        f"📊 <b>نتیجه تمرین نوشتاری</b>\n"
        f"✅ درست: {correct}\n"
        f"❌ غلط: {session.get('wrong', 0)}\n"
        f"🎯 دقت: {int(correct / total * 100) if total else 0}%\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔁 تکرار", callback_data="writing_start:")],
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
        ]
    )

    await render(query, msg, reply_markup=kb)


async def handle_writing_skip(query, context):
    lock_key = "writing_skip_lock"

    if context.user_data.get(lock_key):
        try:
            await query.answer()
        except Exception:
            pass
        return

    context.user_data[lock_key] = True

    try:
        session = context.user_data.get("writing_session")

        if not session:
            return

        word_id = context.user_data.get("writing_current_word")
        word = db.words.get_by_id(word_id)

        if word:
            session["wrong"] = session.get("wrong", 0) + 1

            user_id = query.from_user.id

            record_quiz_answer(
                user_id=user_id,
                word_id=word_id,
                skill_type="writing",
                is_correct=False,
                user_answer="(skipped)",
                correct_answer=word.display_german,
                update_srs=True,
                update_quiz_stats=False,
                xp=0,
                quiz_type="writing",
            )

        session["current"] = session.get("current", 0) + 1
        context.user_data.pop("awaiting_writing_answer", None)

        await _show_writing_question(query, context)

    finally:
        context.user_data.pop(lock_key, None)


async def handle_writing_exit(query, context):
    context.user_data.pop("writing_session", None)
    context.user_data.pop("awaiting_writing_answer", None)
    await render(query, "❌ تمرین نوشتاری لغو شد.", reply_markup=back_inline_keyboard())


async def handle_writing_start(query, context):
    await start_writing_quiz(query, context, count=5)


async def handle_writing_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """وقتی کاربر جواب نوشتاری را تایپ می‌کند."""
    if not context.user_data.get("awaiting_writing_answer"):
        return False

    user_input = update.message.text.strip()
    word_id = context.user_data.get("writing_current_word")
    word = db.words.get_by_id(word_id)

    if not word:
        context.user_data.pop("awaiting_writing_answer", None)
        return True

    user_norm = " ".join(user_input.lower().split())

    is_correct = False
    feedback = ""

    # ✅ حالت ملایم:
    # برای اسم‌ها، اگر آرتیکل ننوشت، درست حساب می‌شود ولی warning می‌گیرد.
    if word.word_type == "Noun" and word.article:
        full_answer = f"{word.article} {word.german}".lower()
        bare_answer = word.german.lower()

        if user_norm == full_answer:
            is_correct = True
            feedback = "✅ آفرین! درست بود."
        elif user_norm == bare_answer:
            is_correct = True
            feedback = (
                "✅ درست بود، ولی بهتر است آرتیکل را هم بنویسی.\n"
                f"⚠️ جواب کامل: <b>{esc(word.display_german)}</b>"
            )
        else:
            feedback = f"❌ اشتباه. جواب درست: <b>{esc(word.display_german)}</b>"
    else:
        correct_variants = {word.german.lower()}

        if word.article:
            correct_variants.add(f"{word.article} {word.german}".lower())

        if user_norm in correct_variants:
            is_correct = True
            feedback = "✅ آفرین! درست بود!"
        else:
            feedback = f"❌ اشتباه. جواب درست: <b>{esc(word.display_german)}</b>"

    session = context.user_data.get("writing_session", {})

    if is_correct:
        session["correct"] = session.get("correct", 0) + 1
    else:
        session["wrong"] = session.get("wrong", 0) + 1

    user_id = update.effective_user.id

    # ✅ ثبت مهارت + mistake + FSRS
    record_quiz_answer(
        user_id=user_id,
        word_id=word_id,
        skill_type="writing",
        is_correct=is_correct,
        user_answer=user_input,
        correct_answer=word.display_german,
        update_srs=True,
        update_quiz_stats=True,
        xp=5 if is_correct else 0,
        quiz_type="writing",
    )

    session["current"] = session.get("current", 0) + 1
    context.user_data.pop("awaiting_writing_answer", None)

    await update.message.reply_text(feedback)

    await _show_writing_question_from_message(update, context)

    return True
