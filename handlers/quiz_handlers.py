from handlers.quiz_questions import QUIZ_REGISTRY
from core.answer_tokens import new_answer_token, answer_index
import logging
import random
import re
from typing import Callable, List, Optional
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import asyncio
import config
from learning_engine import record_quiz_answer
from services import db, llm, run_db
from ui import back_inline_keyboard, esc, quiz_answer_keyboard, render
from core.locks import callback_guard


logger = logging.getLogger(__name__)


def _safe_truncate_html(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text

    plain = re.sub(r"<[^>]+>", "", str(text or ""))
    plain = plain.strip()
    if len(plain) > max_len - 10:
        plain = plain[: max_len - 10] + "\n..."
    return esc(plain)


async def _start_generic_quiz(
    query,
    context,
    word_fetcher: Callable,
    quiz_generator: Callable,
    quiz_type: str,
    source_filter: str = None,
):
    try:
        user_id = query.from_user.id
        lesson_id = context.user_data.get("quiz_lesson_id")

        settings = await run_db(db.users.get_settings, user_id)
        level = settings.get("preferred_level", "A1")

        session = context.user_data.get("quiz_session_obj")
        exclude_ids = set(session.get("question_ids", [])) if session else set()

        word = None
        quiz = None

        for _ in range(10):
            word = await word_fetcher(user_id, lesson_id, source_filter, exclude_ids)
            if not word:
                break

            try:
                t0 = time.time()
                quiz = await quiz_generator(word, user_id, level)
                logger.info(
                    "quiz_generator type=%s word_id=%s took %.2fs",
                    quiz_type,
                    word.id,
                    time.time() - t0,
                )
            except Exception as e:
                logger.error("خطا در quiz_generator: %s", e, exc_info=True)
                quiz = None

            if quiz:
                break

            exclude_ids.add(word.id)

        if not word or not quiz:
            if session and session.get("current_index", 0) > 0:
                await _show_quiz_summary(query, context, header="⚠️ کلمه‌ی مناسب دیگری پیدا نشد.")
            else:
                await render(
                    query,
                    "📭 کلمه‌ای برای این کوییز پیدا نشد.",
                    reply_markup=back_inline_keyboard(),
                )
            return

        token = new_answer_token()
        context.user_data["current_quiz"] = {
            "answer_token": token,
            **quiz,
            "type": quiz_type,
            "word": word.german,
            "word_id": word.id,
            "persian": word.persian,
        }

        flash = context.user_data.pop("quiz_flash", None)
        progress = _get_session_progress(context)

        parts = []
        if flash:
            parts.append(esc(flash))
        if progress:
            parts.append(esc(progress))
        parts.append(quiz.get("question", ""))

        msg = "\n".join(parts)
        context.user_data["quiz_question_sent_at"] = time.time()
        await render(query, msg, reply_markup=quiz_answer_keyboard(quiz.get("options", []), token))

    except Exception as e:
        logger.error("خطای غیرمنتظره در _start_generic_quiz: %s", e, exc_info=True)
        await render(
            query,
            "❌ خطای غیرمنتظره در شروع کوییز.",
            reply_markup=back_inline_keyboard(),
        )


async def start_quiz_by_type(
    query,
    context,
    quiz_type: str,
    source_filter: str = None,
    fixed_word_ids: Optional[List[int]] = None,
):
    if quiz_type not in QUIZ_REGISTRY:
        quiz_type = "meaning"

    quiz_config = QUIZ_REGISTRY[quiz_type]
    word_fetcher = quiz_config.word_fetcher

    if fixed_word_ids:
        fixed_word_ids = list(dict.fromkeys(fixed_word_ids))

        async def fixed_fetcher(user_id, lesson_id, source_filter, exclude_ids):
            exclude = set(exclude_ids or [])
            for wid in fixed_word_ids:
                if wid not in exclude:
                    w = await run_db(db.words.get_by_id, wid)
                    if w:
                        return w
            return None

        word_fetcher = fixed_fetcher

    await _start_generic_quiz(
        query,
        context,
        word_fetcher,
        quiz_config.quiz_generator,
        quiz_type,
        source_filter,
    )


def _init_quiz_session(
    context,
    quiz_type: str,
    total_questions: int,
    source_filter: Optional[str] = None,
    lesson_id: Optional[int] = None,
):
    """Initialize quiz session as a JSON-safe plain dict.

    The session is stored under ``quiz_session_obj`` as a ``dict`` with
    eight primitive/built-in fields, instead of a ``QuizSession``
    dataclass instance.  This keeps ``context.user_data`` JSON-serializable
    so we can later migrate from ``PicklePersistence`` to
    ``JSONPersistence`` without rewriting every consumer.
    """
    # ✅ پاک‌سازی stateهای قدیمی قبل از شروع session جدید
    context.user_data.pop("quiz_wrong_word_ids", None)
    context.user_data.pop("quiz_flash", None)
    context.user_data.pop("quiz_fixed_word_ids", None)
    context.user_data.pop("current_quiz", None)
    context.user_data.pop("quiz_question_sent_at", None)
    context.user_data["quiz_session_obj"] = {
        "quiz_type": str(quiz_type),
        "total_questions": int(total_questions),
        "current_index": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "question_ids": [],
        "source_filter": source_filter,
        "lesson_id": lesson_id,
    }


def _get_quiz_session(context) -> Optional[dict]:
    """Get current quiz session dict (or ``None`` if not started)."""
    return context.user_data.get("quiz_session_obj")


def _update_quiz_session(
    context,
    is_correct: bool,
    word: str,
    word_id: Optional[int],
    user_answer: str,
    correct_answer: str,
):
    session = _get_quiz_session(context)
    if not session:
        return
    session["current_index"] += 1
    if is_correct:
        session["correct_count"] += 1
    else:
        session["wrong_count"] += 1
    if word_id:
        # Coerce a stale dataclass value back into a list so the dict
        # shape stays consistent for subsequent writes.
        qids = session.get("question_ids")
        if not isinstance(qids, list):
            qids = []
            session["question_ids"] = qids
        qids.append(word_id)
        # ردیابی کلمات اشتباه در context (نه روی session dict)
        if not is_correct:
            wrong_ids = context.user_data.setdefault("quiz_wrong_word_ids", [])
            if word_id not in wrong_ids:
                wrong_ids.append(word_id)


def _get_session_progress(context) -> str:
    """Get formatted progress string for quiz session."""
    from ui import progress_bar

    session = _get_quiz_session(context)
    if not session:
        return ""
    cur = int(session.get("current_index", 0)) + 1
    tot = int(session.get("total_questions") or 1)
    bar = progress_bar(cur, tot)
    return (
        f"[{bar}] سوال {cur} از {tot} | "
        f"✅ {session.get('correct_count', 0)} | "
        f"❌ {session.get('wrong_count', 0)}"
    )


def _is_session_finished(context) -> bool:
    """Check if quiz session is complete."""
    session = _get_quiz_session(context)
    if not session:
        return True
    return int(session.get("current_index", 0)) >= int(session.get("total_questions", 0))


async def _show_quiz_summary(query, context, header: str = ""):
    session = context.user_data.pop("quiz_session_obj", None)
    context.user_data.pop("current_quiz", None)
    context.user_data.pop("quiz_fixed_word_ids", None)

    if not session:
        await render(query, "🏁 کوییز تمام شد.", reply_markup=back_inline_keyboard())
        return

    wrong_ids = context.user_data.get("quiz_wrong_word_ids", [])

    if not wrong_ids:
        context.user_data.pop("quiz_wrong_word_ids", None)

    correct_count = int(session.get("correct_count", 0))
    wrong_count = int(session.get("wrong_count", 0))
    total_questions = int(session.get("total_questions", 0))

    answered = correct_count + wrong_count

    accuracy = (correct_count / answered * 100) if answered > 0 else 0

    lines = []

    if header:
        lines.append(header)

    lines.append("<b>🏁 کوییز تمام شد!</b>")

    if answered < total_questions:
        lines.append(f"📊 پاسخ داده‌شده: {answered} از {total_questions}")

    lines.append(f"✅ درست: {correct_count}")
    lines.append(f"❌ اشتباه: {wrong_count}")
    lines.append(f"🎯 دقت: {accuracy:.1f}%")

    text = "\n".join(lines)

    if len(text) > 4000:
        text = _safe_truncate_html(text, 4000)

    keyboard = []

    if wrong_ids:
        keyboard.append([InlineKeyboardButton("🔁 فقط اشتباه‌ها", callback_data="quiz_retry_wrong")])

    keyboard.append([InlineKeyboardButton("🔄 کوییز جدید", callback_data="show_quiz_menu")])

    keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")])

    await render(query, text, reply_markup=InlineKeyboardMarkup(keyboard))


@callback_guard("quiz_answer_lock")
async def handle_quiz_answer(query, context):
    if "current_quiz" not in context.user_data:
        try:
            await query.answer("⚠️ کوییز فعال نیست.", show_alert=True)
        except Exception:
            pass
        return

    quiz_info = context.user_data["current_quiz"]

    try:
        chosen_index = answer_index(query.data.split(":", 1)[1], quiz_info)
    except (ValueError, IndexError):
        await query.answer("⚠️ گزینه نامعتبر.", show_alert=True)
        return

    options = quiz_info.get("options", [])
    if chosen_index < 0 or chosen_index >= len(options):
        await query.answer("⚠️ گزینه نامعتبر.", show_alert=True)
        return

    user_id = query.from_user.id
    is_correct = chosen_index == quiz_info["correct_index"]
    user_answer_text = options[chosen_index]
    sent_at = context.user_data.get("quiz_question_sent_at")
    response_time = None
    if sent_at:
        response_time = time.time() - sent_at
    correct_answer = quiz_info.get("correct_answer") or options[quiz_info["correct_index"]]

    quiz_type = quiz_info.get("type", "meaning")

    await run_db(
        record_quiz_answer,
        user_id=user_id,
        word_id=quiz_info.get("word_id"),
        skill_type=quiz_type,
        is_correct=is_correct,
        user_answer=user_answer_text,
        correct_answer=correct_answer,
        update_srs=True,
        update_quiz_stats=True,
        xp=5 if is_correct else 0,
        quiz_type=quiz_type,
        response_time_sec=response_time,
    )
    context.user_data.pop("quiz_question_sent_at", None)
    _update_quiz_session(
        context,
        is_correct,
        quiz_info.get("word", ""),
        quiz_info.get("word_id"),
        user_answer_text,
        correct_answer,
    )

    context.user_data.pop("current_quiz", None)

    if is_correct:
        try:
            await query.answer("✅ درست بود!", show_alert=False)
        except Exception:
            pass

        if config.QUIZ_AUTO_NEXT_ON_CORRECT:
            if _is_session_finished(context):
                await _show_quiz_summary(query, context)
            else:
                context.user_data["quiz_flash"] = "✅ درست بود!"
                await _send_next_quiz(query, context)
            return

        feedback = "✅ آفرین! جواب درست بود! 🎉"
    else:
        try:
            await query.answer("❌ اشتباه بود", show_alert=False)
        except Exception:
            pass

        feedback = f"❌ اشتباه بود!\n✅ جواب درست: {esc(correct_answer)}"

        if config.QUIZ_LLM_EXPLAIN_MISTAKE and llm.is_available():
            try:
                explanation = await asyncio.wait_for(
                    llm.explain_mistake(
                        quiz_info.get("word", ""),
                        user_answer_text,
                        correct_answer,
                        quiz_info.get("type", "meaning"),
                    ),
                    timeout=config.QUIZ_LLM_TIMEOUT_SECONDS,
                )

                if explanation:
                    feedback += f"\n💡 {esc(explanation)}"

            except Exception as e:
                logger.warning("LLM explain mistake timeout/fallback: %s", e)

    if _is_session_finished(context):
        await _show_quiz_summary(query, context, header=feedback)
    else:
        progress = _get_session_progress(context)
        text = feedback
        if progress:
            text += f"\n{esc(progress)}"

        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⏭️ سوال بعدی", callback_data="quiz_next")],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
            ]
        )

        await render(query, text, reply_markup=kb)


async def start_quiz_session(
    query,
    context,
    quiz_type: str = "meaning",
    count: int = 10,
    source_filter: str = None,
):
    if quiz_type not in QUIZ_REGISTRY:
        quiz_type = "meaning"
    lesson_id = context.user_data.get("quiz_lesson_id")
    _init_quiz_session(context, quiz_type, count, source_filter, lesson_id)
    context.user_data["quiz_type"] = quiz_type
    context.user_data["quiz_source_filter"] = source_filter
    context.user_data.pop("quiz_fixed_word_ids", None)
    await _send_next_quiz(query, context)


async def start_wrong_quiz(query, context):
    wrong_ids = list(dict.fromkeys(context.user_data.get("quiz_wrong_word_ids", [])))
    if not wrong_ids:
        await render(query, "📭 لیست اشتباه‌ها موجود نیست.", reply_markup=back_inline_keyboard())
        return

    words = await run_db(db.words.get_by_ids, wrong_ids)
    if not words:
        await render(
            query,
            "📭 کلمه‌ای برای مرور اشتباه‌ها پیدا نشد.",
            reply_markup=back_inline_keyboard(),
        )
        return

    random.shuffle(words)

    # ✅ همیشه meaning برای retry wrong (امن برای همه نوع کلمه)
    _init_quiz_session(context, "meaning", len(words), None, None)
    context.user_data["quiz_fixed_word_ids"] = [w.id for w in words]
    context.user_data["quiz_type"] = "meaning"
    context.user_data["quiz_source_filter"] = None
    context.user_data.pop("quiz_lesson_id", None)

    await _send_next_quiz(query, context)


async def _send_next_quiz(query, context):
    if "quiz_session_obj" not in context.user_data:
        await render(query, "⚠️ کوییزی فعال نیست. /menu", reply_markup=back_inline_keyboard())
        return

    quiz_type = context.user_data.get("quiz_type", "meaning")
    source_filter = context.user_data.get("quiz_source_filter")
    fixed_word_ids = context.user_data.get("quiz_fixed_word_ids")

    await start_quiz_by_type(query, context, quiz_type, source_filter, fixed_word_ids)
