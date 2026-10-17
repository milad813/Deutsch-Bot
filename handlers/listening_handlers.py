"""Listening practice - play audio, user selects meaning."""

import logging
import random

from core.answer_tokens import new_answer_token, answer_index

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from core.locks import callback_guard
from core.callbacks import cb_safe
from models import CallbackPrefix

from learning_engine import record_quiz_answer
from option_generator import get_wrong_options
from services import db, tts, run_db
from ui import _short_label, back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)


async def start_listening_quiz(query, context, count: int = 5):
    """شروع تمرین شنیداری."""
    context.user_data.pop("listening_session", None)
    context.user_data.pop("listening_current", None)
    count = max(1, min(int(count), 50))
    user_id = query.from_user.id
    lesson_id = context.user_data.get("quiz_lesson_id")

    words = await run_db(db.words.get_due, user_id, limit=count, lesson_id=lesson_id)
    if not words:
        words = await run_db(
            db.words.get_new_word_objects, user_id, lesson_id=lesson_id, limit=count
        )

    if not words:
        await render(query, "📭 کلمه‌ای برای تمرین نیست.", reply_markup=back_inline_keyboard())
        return

    random.shuffle(words)
    context.user_data["listening_session"] = {
        "words": [w.id for w in words],
        "current": 0,
        "correct": 0,
        "wrong": 0,
        "skipped": 0,
        "unavailable": 0,
    }

    await _show_listening_question(query, context)


async def _show_listening_question(update, context):
    """Advance iteratively through unavailable items without growing the stack."""
    session = context.user_data.get("listening_session")
    while session and session["current"] < len(session["words"]):
        word_id = session["words"][session["current"]]
        word = await run_db(db.words.get_by_id, word_id)
        if not word:
            session["current"] += 1
            continue

        wrong_options = await run_db(
            get_wrong_options, db, word, count=3, attr_getter=lambda w: w.persian
        )
        options = [word.persian] + wrong_options[:3]
        options = list(dict.fromkeys([str(o).strip() for o in options if str(o).strip()]))

        if len(options) < 2:
            session["current"] += 1
            context.user_data.pop("listening_current", None)
            # ✅ به‌جای query.answer، از render استفاده کن
            continue

        random.shuffle(options)
        correct_idx = options.index(word.persian)

        # تولید و ارسال صدا
        audio_path = await tts.get_audio_path(word.display_german)
        audio_sent = False
        if audio_path:
            try:
                chat_id = None
                # پشتیبانی از هر دو query و message
                if hasattr(update, "message") and update.message:
                    chat_id = update.message.chat_id
                elif hasattr(update, "effective_message") and update.effective_message:
                    chat_id = update.effective_message.chat_id

                if chat_id:
                    with open(audio_path, "rb") as f:
                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=f,
                            title="Listening exercise",
                        )
                    audio_sent = True
            except Exception as e:
                logger.warning("خطا در ارسال فایل صوتی: %s", e)

        if not audio_sent:
            session["unavailable"] = session.get("unavailable", 0) + 1
            session["current"] += 1
            context.user_data.pop("listening_current", None)
            continue

        token = new_answer_token()
        context.user_data["listening_current"] = {
            "answer_token": token,
            "word_id": word_id,
            "correct_index": correct_idx,
            "options": options,
        }

        msg = (
            f"🎧 <b>تمرین شنیداری</b> ({session['current'] + 1}/{len(session['words'])})"
            f"\nصدا را گوش بده و معنی فارسی را انتخاب کن:"
        )
        kb_rows = []
        for i, opt in enumerate(options):
            kb_rows.append(
                [
                    InlineKeyboardButton(
                        _short_label(opt, 64),
                        callback_data=cb_safe(CallbackPrefix.LISTENING_ANS, f"{token}:{i}"),
                    )
                ]
            )
        kb_rows.append(
            [
                InlineKeyboardButton(
                    "🔊 پخش دوباره", callback_data=cb_safe(CallbackPrefix.LISTENING_REPLAY, token)
                )
            ]
        )
        kb_rows.append(
            [
                InlineKeyboardButton(
                    "⏭️ رد شدن", callback_data=cb_safe(CallbackPrefix.LISTENING_SKIP, token)
                )
            ]
        )
        kb_rows.append([InlineKeyboardButton("🏁 پایان", callback_data="listening_exit:")])
        await render(update, msg, reply_markup=InlineKeyboardMarkup(kb_rows))

        return
    await _show_listening_summary(update, context)


async def _show_listening_summary(query, context):
    session = context.user_data.pop("listening_session", {})
    context.user_data.pop("listening_current", None)
    total = session.get("correct", 0) + session.get("wrong", 0)
    correct = session.get("correct", 0)

    msg = (
        f"📊 <b>نتیجه تمرین شنیداری</b>\n"
        f"✅ درست: {correct}\n"
        f"❌ غلط: {session.get('wrong', 0)}\n"
        f"⏭️ ردشده بدون امتیاز: {session.get('skipped', 0)}\n"
        f"🔇 صدای در دسترس نبود: {session.get('unavailable', 0)}\n"
        f"🎯 دقت: {int(correct / total * 100) if total else 0}%\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔁 تکرار", callback_data="listening_start:")],
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
        ]
    )

    await render(query, msg, reply_markup=kb)


_listening_guard = callback_guard("listening_answer_lock")


@_listening_guard
async def handle_listening_answer(query, context, suffix: str):
    current = context.user_data.get("listening_current")
    session = context.user_data.get("listening_session")
    if not current or not session:
        return
    try:
        selected_idx = answer_index(suffix, current)
    except (ValueError, TypeError):
        await query.answer("Expired or invalid answer", show_alert=True)
        return

    options = current.get("options", [])

    if selected_idx < 0 or selected_idx >= len(options):
        try:
            await query.answer("⚠️ گزینه نامعتبر.", show_alert=True)
        except Exception:
            pass
        return

    word_id = current["word_id"]
    word = await run_db(db.words.get_by_id, word_id)

    if not word:
        return

    is_correct = selected_idx == current["correct_index"]

    if is_correct:
        feedback = "✅ آفرین! درست بود!"
    else:
        correct_opt = options[current["correct_index"]]
        feedback = f"❌ اشتباه. جواب درست: <b>{esc(correct_opt)}</b>"

    user_id = query.from_user.id

    # ✅ ثبت مهارت + mistake + FSRS
    await run_db(
        record_quiz_answer,
        user_id=user_id,
        word_id=word_id,
        skill_type="listening",
        is_correct=is_correct,
        user_answer=options[selected_idx],
        correct_answer=word.persian,
        update_srs=True,
        update_quiz_stats=True,
        xp=5 if is_correct else 0,
        quiz_type="listening",
    )

    key = "correct" if is_correct else "wrong"
    session[key] = session.get(key, 0) + 1
    session["current"] = session.get("current", 0) + 1
    context.user_data.pop("listening_current", None)

    try:
        await query.answer(feedback, show_alert=False)
    except Exception:
        pass

    await _show_listening_question(query, context)


@_listening_guard
async def handle_listening_skip(query, context, suffix: str = ""):
    session = context.user_data.get("listening_session")
    current = context.user_data.get("listening_current")
    if not session or not current or suffix != current.get("answer_token"):
        return
    # A situational skip is not evidence that the learner forgot the word.
    session["skipped"] = session.get("skipped", 0) + 1
    session["current"] += 1
    context.user_data.pop("listening_current", None)
    await _show_listening_question(query, context)


@_listening_guard
async def handle_listening_exit(query, context):
    context.user_data.pop("listening_session", None)
    context.user_data.pop("listening_current", None)
    await render(query, "تمرین شنیداری پایان یافت.", reply_markup=back_inline_keyboard())


async def handle_listening_start(query, context):
    await start_listening_quiz(query, context, count=5)


async def handle_listening_replay(query, context, suffix: str):
    """پخش دوباره صدا."""
    current = context.user_data.get("listening_current")
    if not current or suffix != current.get("answer_token"):
        return
    word_id = current["word_id"]

    word = await run_db(db.words.get_by_id, word_id)
    if not word:
        return

    audio_path = await tts.get_audio_path(word.display_german)

    if not audio_path:
        try:
            await query.answer("❌ صدا در دسترس نیست.", show_alert=True)
        except Exception:
            pass
        return

    try:
        with open(audio_path, "rb") as f:
            await context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=f,
                title="Listening exercise",
            )
    except Exception as e:
        logger.warning("خطا در پخش دوباره صدا: %s", e)
        try:
            await query.answer("❌ خطا در پخش صدا.", show_alert=True)
        except Exception:
            pass
        return

    await query.answer()
