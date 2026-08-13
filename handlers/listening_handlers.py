"""Listening practice - play audio, user selects meaning."""
import logging
import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from services import db, tts
from learning_engine import record_quiz_answer
from ui import _short_label, back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)


def _get_wrong_persian(word):
    """گزینه‌های غلط بدون لود کل دیتابیس."""
    wrong_words = db.get_words_by_type(
        word.word_type, exclude_id=word.id, limit=50
    )
    if len(wrong_words) < 3:
        wrong_words += db.get_words_by_type(None, exclude_id=word.id, limit=50)
    wrong = [w.persian for w in wrong_words if w.persian and w.persian != word.persian]
    wrong = list(dict.fromkeys(wrong))  # حذف تکراری
    random.shuffle(wrong)
    return wrong[:3]


async def start_listening_quiz(query, context, count: int = 5):
    """شروع تمرین شنیداری."""
    user_id = query.from_user.id
    lesson_id = context.user_data.get("quiz_lesson_id")
    
    words = db.get_due_word_objects(user_id, limit=count, lesson_id=lesson_id)
    if not words:
        words = db.get_new_word_objects(user_id, lesson_id=lesson_id, limit=count)
    
    if not words:
        await render(query, "📭 کلمه‌ای برای تمرین نیست.", reply_markup=back_inline_keyboard())
        return
    
    random.shuffle(words)
    context.user_data["listening_session"] = {
        "words": [w.id for w in words],
        "current": 0,
        "correct": 0,
        "wrong": 0,
    }
    
    await _show_listening_question(query, context)

async def _show_listening_question(query, context):
    session = context.user_data.get("listening_session")

    if not session or session["current"] >= len(session["words"]):
        await _show_listening_summary(query, context)
        return

    word_id = session["words"][session["current"]]
    word = db.get_word_by_id(word_id)

    if not word:
        session["current"] += 1
        await _show_listening_question(query, context)
        return

    # اول گزینه‌ها را آماده کن؛ اگر گزینه کافی نبود، سوال کلاً رد شود
    wrong_options = _get_wrong_persian(word)
    options = [word.persian] + wrong_options[:3]

    options = list(
        dict.fromkeys(
            [str(o).strip() for o in options if str(o).strip()]
        )
    )

    if len(options) < 2:
        session["current"] += 1
        context.user_data.pop("listening_current", None)

        try:
            await query.answer("⚠️ گزینه کافی برای این کلمه وجود ندارد؛ سوال رد شد.", show_alert=False)
        except Exception:
            pass

        await _show_listening_question(query, context)
        return

    random.shuffle(options)
    correct_idx = options.index(word.persian)

    # تولید و ارسال صدا
    audio_path = await tts.get_audio_path(word.display_german)
    audio_sent = False

    if audio_path:
        try:
            with open(audio_path, "rb") as f:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=f,
                    title=word.display_german,
                )
            audio_sent = True
        except Exception as e:
            logger.warning("خطا در ارسال فایل صوتی: %s", e)

    # اگر صدا ارسال نشد، سوال بدون صدا نمایش داده نشود
    if not audio_sent:
        session["current"] += 1
        context.user_data.pop("listening_current", None)

        try:
            await query.answer("⚠️ صدا در دسترس نیست؛ سوال رد شد.", show_alert=False)
        except Exception:
            pass

        await _show_listening_question(query, context)
        return

    context.user_data["listening_current"] = {
        "word_id": word_id,
        "correct_index": correct_idx,
        "options": options,
    }

    msg = (
        f"🎧 <b>تمرین شنیداری</b> ({session['current']+1}/{len(session['words'])})\n"
        f"صدا را گوش بده و معنی فارسی را انتخاب کن:"
    )

    kb_rows = []

    for i, opt in enumerate(options):
        kb_rows.append([
            InlineKeyboardButton(
                _short_label(f"{chr(65+i)}) {opt}", 64),
                callback_data=f"listening_ans:{i}"
            )
        ])

    kb_rows.append([
        InlineKeyboardButton("🔊 پخش دوباره", callback_data=f"listening_replay:{word_id}")
    ])

    kb_rows.append([
        InlineKeyboardButton("⏭️ رد شدن", callback_data="listening_skip:")
    ])

    kb_rows.append([
        InlineKeyboardButton("🏁 پایان", callback_data="listening_exit:")
    ])

    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb_rows))

async def _show_listening_question_from_message(update, context):
    """ادامه سوال بعدی از پیام متنی."""
    class FakeQuery:
        def __init__(self, update):
            self.from_user = update.effective_user
            self.message = update.message
            self.data = ""
        async def answer(self, text=None, show_alert=False):
            pass
    query = FakeQuery(update)
    await _show_listening_question(query, context)

async def _show_listening_summary(query, context):
    session = context.user_data.pop("listening_session", {})
    total = session.get("correct", 0) + session.get("wrong", 0)
    correct = session.get("correct", 0)
    
    msg = (
        f"📊 <b>نتیجه تمرین شنیداری</b>\n"
        f"✅ درست: {correct}\n"
        f"❌ غلط: {session.get('wrong', 0)}\n"
        f"🎯 دقت: {int(correct / total * 100) if total else 0}%\n"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 تکرار", callback_data="listening_start:")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
    ])
    
    await render(query, msg, reply_markup=kb)

async def handle_listening_answer(query, context, suffix: str):
    """پردازش جواب کاربر."""
    lock_key = "listening_answer_lock"

    if context.user_data.get(lock_key):
        try:
            await query.answer()
        except Exception:
            pass
        return

    context.user_data[lock_key] = True

    try:
        try:
            selected_idx = int(suffix)
        except (ValueError, TypeError):
            try:
                await query.answer("⚠️ گزینه نامعتبر.", show_alert=True)
            except Exception:
                pass
            return

        current = context.user_data.get("listening_current")
        session = context.user_data.get("listening_session")

        if not current or not session:
            return

        options = current.get("options", [])

        if selected_idx < 0 or selected_idx >= len(options):
            try:
                await query.answer("⚠️ گزینه نامعتبر.", show_alert=True)
            except Exception:
                pass
            return

        word_id = current["word_id"]
        word = db.get_word_by_id(word_id)

        if not word:
            return

        is_correct = selected_idx == current["correct_index"]

        if is_correct:
            session["correct"] = session.get("correct", 0) + 1
            feedback = "✅ آفرین! درست بود!"
        else:
            session["wrong"] = session.get("wrong", 0) + 1
            correct_opt = options[current["correct_index"]]
            feedback = f"❌ اشتباه. جواب درست: <b>{esc(correct_opt)}</b>"

        user_id = query.from_user.id

        # ✅ ثبت مهارت + mistake + FSRS
        record_quiz_answer(
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

        session["current"] = session.get("current", 0) + 1
        context.user_data.pop("listening_current", None)

        try:
            await query.answer(feedback, show_alert=False)
        except Exception:
            pass

        await _show_listening_question(query, context)

    finally:
        context.user_data.pop(lock_key, None)

async def handle_listening_skip(query, context):
    lock_key = "listening_skip_lock"

    if context.user_data.get(lock_key):
        try:
            await query.answer()
        except Exception:
            pass
        return

    context.user_data[lock_key] = True

    try:
        session = context.user_data.get("listening_session")

        if not session:
            return

        current = context.user_data.get("listening_current")

        if current:
            word_id = current["word_id"]
            word = db.get_word_by_id(word_id)

            if word:
                session["wrong"] = session.get("wrong", 0) + 1

                user_id = query.from_user.id

                # ✅ skip روی FSRS اثر بگذارد، ولی در آمار کلی کوییز ثبت نشود
                record_quiz_answer(
                    user_id=user_id,
                    word_id=word_id,
                    skill_type="listening",
                    is_correct=False,
                    user_answer="(skipped)",
                    correct_answer=word.persian,
                    update_srs=True,
                    update_quiz_stats=False,
                    xp=0,
                    quiz_type="listening",
                )

        session["current"] = session.get("current", 0) + 1
        context.user_data.pop("listening_current", None)

        await _show_listening_question(query, context)

    finally:
        context.user_data.pop(lock_key, None)

async def handle_listening_exit(query, context):
    context.user_data.pop("listening_session", None)
    context.user_data.pop("listening_current", None)
    await render(query, "❌ تمرین شنیداری لغو شد.", reply_markup=back_inline_keyboard())


async def handle_listening_start(query, context):
    await start_listening_quiz(query, context, count=5)


async def handle_listening_replay(query, context, suffix: str):
    """پخش دوباره صدا."""
    try:
        word_id = int(suffix)
    except (ValueError, TypeError):
        return

    word = db.get_word_by_id(word_id)
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
                title=word.display_german,
            )
    except Exception as e:
        logger.warning("خطا در پخش دوباره صدا: %s", e)
        try:
            await query.answer("❌ خطا در پخش صدا.", show_alert=True)
        except Exception:
            pass
        return

    await query.answer()