import logging
from typing import Callable, Dict, List, Tuple

from telegram.error import BadRequest

import config
from handlers import grammar_handlers, menus, quiz_handlers, story_handlers
from handlers.learning import (FlashcardSessionManager, handle_flip_card,
                               handle_next_flashcard, handle_rate_card,
                               handle_skip_flashcard, start_flashcard_session)
from handlers.learning.ltr_session import LTRSessionManager
from services import db, get_main_menu_keyboard, reset_session, tts
from ui import back_inline_keyboard, render

logger = logging.getLogger(__name__)

_tts_jobs: Dict[int, object] = {}


async def _cleanup_tts(context, user_id: int):
    job = _tts_jobs.pop(user_id, None)
    if job:
        try:
            job.schedule_removal()
        except Exception:
            pass
    info = context.user_data.pop("tts_message", None)
    if info:
        try:
            await context.bot.delete_message(chat_id=info[0], message_id=info[1])
        except Exception:
            pass


async def _auto_delete_tts(context):
    chat_id, message_id = context.job.data
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _send_ephemeral_audio(query, context, text):
    if not query or not query.message:
        return
    user_id = query.from_user.id
    await _cleanup_tts(context, user_id)
    audio_path = await tts.get_audio_path(text)
    if not audio_path:
        await query.message.reply_text("❌ قابلیت تلفظ در دسترس نیست.")
        return
    chat_id = query.message.chat_id
    title = text if len(text) <= 80 else text[:77] + "..."
    try:
        with open(audio_path, "rb") as f:
            if config.TTS_SEND_AS_DOCUMENT:
                sent = await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    caption=f"🔊 {title}",
                    reply_to_message_id=query.message.message_id,
                    allow_sending_without_reply=True,
                    disable_content_type_detection=True,
                )
            else:
                sent = await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    title=title,
                    performer="German Bot",
                    reply_to_message_id=query.message.message_id,
                    allow_sending_without_reply=True,
                )
    except Exception as e:
        logger.error("Failed to send audio: %s", e)
        await query.message.reply_text("❌ خطا در پخش صدا")
        return

    context.user_data["tts_message"] = (chat_id, sent.message_id)
    if config.TTS_AUTO_DELETE_SECONDS > 0 and context.job_queue:
        job = context.job_queue.run_once(
            _auto_delete_tts,
            config.TTS_AUTO_DELETE_SECONDS,
            data=(chat_id, sent.message_id),
            chat_id=chat_id,
            user_id=user_id,
        )
        _tts_jobs[user_id] = job


async def _handle_speak_current(query, context, suffix: str):
    text = context.user_data.get("current_tts_text")
    if not text:
        fc = context.user_data.get("current_flashcard") or {}
        word_id = fc.get("word_id")
        word = db.get_word_by_id(word_id) if word_id else None
        text = word.display_german if word else None
    if not text:
        try:
            await query.answer("❌ متن تلفظ موجود نیست.", show_alert=True)
        except Exception:
            pass
        return
    await _send_ephemeral_audio(query, context, text)


async def _handle_quiz_type(query, context, suffix: str):
    context.user_data["quiz_type"] = suffix
    if context.user_data.pop("quiz_lesson_preset", False):
        await menus.show_quiz_count(query, context)
        return
    context.user_data.pop("quiz_lesson_id", None)
    context.user_data.pop("quiz_source_filter", None)
    await menus.show_quiz_source(query, context)


async def _handle_quiz_from_lesson(query, context, suffix: str):
    try:
        lesson_id = int(suffix)
    except ValueError:
        return
    context.user_data["quiz_lesson_id"] = lesson_id
    context.user_data["quiz_lesson_preset"] = True
    context.user_data.pop("quiz_source_filter", None)
    await menus.show_quiz_menu(query, context)


async def _handle_flashcard_lesson(query, context, suffix: str):
    try:
        lesson_id = int(suffix)
    except ValueError:
        return
    await learning_handlers.start_flashcard_session(query, context, lesson_id=lesson_id)


async def _handle_study_lesson(query, context, suffix: str):
    try:
        lesson_id = int(suffix)
    except ValueError:
        return
    await learning_handlers.start_study_session(query, context, lesson_id=lesson_id)


async def _handle_quiz_source(query, context, suffix: str):
    if suffix == "all":
        context.user_data.pop("quiz_lesson_id", None)
        context.user_data.pop("quiz_source_filter", None)
        await menus.show_quiz_count(query, context)
    elif suffix == "lesson":
        context.user_data.pop("quiz_source_filter", None)
        context.user_data.pop("quiz_lesson_id", None)
        await menus.show_books_for_quiz(query, context)
    elif suffix == "weak":
        context.user_data.pop("quiz_lesson_id", None)
        context.user_data["quiz_source_filter"] = "weak"
        await menus.show_quiz_count(query, context)
    elif suffix == "due":
        context.user_data.pop("quiz_lesson_id", None)
        context.user_data["quiz_source_filter"] = "due"
        await menus.show_quiz_count(query, context)


async def _handle_quiz_count(query, context, suffix: str):
    user_id = query.from_user.id
    lesson_id = context.user_data.get("quiz_lesson_id")
    source_filter = context.user_data.get("quiz_source_filter")

    if suffix == "all":
        if lesson_id:
            count = db.get_word_count_by_lesson(lesson_id)
        elif source_filter == "weak":
            count = db.get_weak_word_count(user_id)
        elif source_filter == "due":
            count = db.get_due_word_count(user_id)
        else:
            count = db.get_word_count()
        count = min(count, config.MAX_QUIZ_ALL_COUNT)
    else:
        try:
            count = int(suffix)
        except ValueError:
            count = 10
        count = max(1, min(count, config.MAX_QUIZ_ALL_COUNT))

    if count <= 0:
        await render(
            query,
            "📭 کلمه‌ای در این منبع وجود ندارد!",
            reply_markup=back_inline_keyboard(),
        )
        return

    quiz_type = context.user_data.get("quiz_type", "meaning")
    await quiz_handlers.start_quiz_session(
        query, context, quiz_type, count, source_filter
    )


async def _handle_quiz_book(query, context, suffix: str):
    try:
        book_id = int(suffix)
    except ValueError:
        return
    await menus.show_lessons_for_quiz(query, context, book_id)


async def _handle_quiz_lesson(query, context, suffix: str):
    try:
        lesson_id = int(suffix)
    except ValueError:
        return
    context.user_data["quiz_lesson_id"] = lesson_id
    await menus.show_quiz_count(query, context)


async def _handle_quiz_ans(query, context, suffix: str):
    await quiz_handlers.handle_quiz_answer(query, context)


async def _handle_lesson_words(query, context, suffix: str):
    try:
        parts = suffix.split("_")
        lesson_id = int(parts[0])
        page = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return
    await menus.show_lesson_words(query, context, lesson_id, page=page)


async def _handle_book(query, context, suffix: str):
    try:
        book_id = int(suffix)
    except ValueError:
        return
    await menus.show_lessons(query, context, book_id)


async def _handle_back_to_main_menu(query, context):
    await _cleanup_tts(context, query.from_user.id)
    reset_session(context)
    try:
        if query.message:
            await context.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
            )
    except Exception:
        pass
    if query.message:
        due_count = db.get_due_word_count(query.from_user.id)
        hard_count = db.count_hard_due_words(query.from_user.id)
        if hard_count > 0:
            msg = f"🏠 <b>منوی اصلی</b>\n🔥 {hard_count} کلمه سخت معوق داری!"
        elif due_count > 0:
            msg = f"🏠 <b>منوی اصلی</b>\n📅 {due_count} کلمه برای مرور داری!"
        else:
            msg = "🏠 <b>منوی اصلی</b>\n🎉 همه مرورها انجام شده!"
        await query.message.reply_text(
            msg, reply_markup=get_main_menu_keyboard(due_count, hard_count=hard_count)
        )


EXACT_ROUTES: Dict[str, Callable] = {
    "back_to_main_menu": None,
    "noop": None,
    "quiz_next": lambda q, c: quiz_handlers._send_next_quiz(q, c),
    "show_books_inline": lambda q, c: menus.show_books(q, c, is_message=False),
    "show_quiz_source": lambda q, c: menus.show_quiz_source(q, c),
    "show_quiz_menu": lambda q, c: menus.show_quiz_menu(q, c),
    "show_settings": lambda q, c: menus.show_settings_menu(q, c),
    "show_level_select": lambda q, c: menus.show_level_select(q, c),
    "quiz_retry_wrong": lambda q, c: quiz_handlers.start_wrong_quiz(q, c),
    "next_flashcard": lambda q, c: learning_handlers.handle_next_flashcard(q, c),
    "ltr_start": lambda q, c: learning_handlers.handle_ltr_start(q, c),
    "ltr_ready": lambda q, c: learning_handlers.handle_ltr_ready(q, c),
    "ltr_summary": lambda q, c: learning_handlers.handle_ltr_summary(q, c),
    "ltr_exit": lambda q, c: learning_handlers.handle_ltr_exit(q, c),
    "flashcard_due": lambda q, c: learning_handlers.start_flashcard_session(
        q, c, only_due=True
    ),
    "flashcard_hard": lambda q, c: learning_handlers.start_flashcard_session(
        q, c, hard_only=True
    ),
}

PREFIX_ROUTES: List[Tuple[str, Callable]] = [
    ("quiz_type:", _handle_quiz_type),
    ("quiz_source:", _handle_quiz_source),
    ("quiz_count:", _handle_quiz_count),
    ("quiz_book:", _handle_quiz_book),
    ("quiz_lesson:", _handle_quiz_lesson),
    ("quiz_ans:", _handle_quiz_ans),
    ("quiz_from_lesson:", _handle_quiz_from_lesson),
    ("flashcard_lesson:", _handle_flashcard_lesson),
    ("study_lesson:", _handle_study_lesson),
    ("flip_card:", lambda q, c, s: learning_handlers.handle_flip_card(q, c, s)),
    (
        "skip_flashcard:",
        lambda q, c, s: learning_handlers.handle_skip_flashcard(q, c, s),
    ),
    ("rate_card:", lambda q, c, s: learning_handlers.handle_rate_card(q, c, s)),
    ("speak_current:", _handle_speak_current),
    ("lesson_words_", _handle_lesson_words),
    ("book_", _handle_book),
    ("lesson_", lambda q, c, s: menus.show_lesson_options(q, c, int(s))),
    ("ltr_ans:", lambda q, c, s: learning_handlers.handle_ltr_answer(q, c, s)),
    (
        "grammar_lesson:",
        lambda q, c, s: grammar_handlers.show_grammar_menu(q, c, int(s)),
    ),
    (
        "grammar_point:",
        lambda q, c, s: grammar_handlers.show_grammar_point(q, c, int(s)),
    ),
    (
        "grammar_quiz:",
        lambda q, c, s: grammar_handlers.start_grammar_quiz(q, c, int(s)),
    ),
    ("grammar_ans:", lambda q, c, s: grammar_handlers.handle_grammar_answer(q, c, s)),
    ("story_lesson:", lambda q, c, s: story_handlers.show_story_menu(q, c, int(s))),
    ("story_view:", lambda q, c, s: story_handlers.show_story(q, c, int(s))),
    ("story_fa:", lambda q, c, s: story_handlers.show_story_translation(q, c, int(s))),
    ("story_words:", lambda q, c, s: story_handlers.show_story_words(q, c, int(s))),
    ("story_audio:", lambda q, c, s: story_handlers.play_story_audio(q, c, int(s))),
    ("story_quiz:", lambda q, c, s: story_handlers.start_story_quiz(q, c, int(s))),
    ("story_ans:", lambda q, c, s: story_handlers.handle_story_answer(q, c, s)),
    ("set_level:", lambda q, c, s: menus.handle_set_level(q, c, s)),
]


async def inline_handler(update, context):
    query = update.callback_query
    data = query.data

    if not query.from_user or not config.is_authorized_user(query.from_user.id):
        try:
            await query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        except Exception:
            pass
        return

    if data == "back_to_main_menu":
        return await _handle_back_to_main_menu(query, context)

    if data == "noop":
        try:
            await query.answer()
        except Exception:
            pass
        return

    # ─── باگ‌فیکس: story_ans هم باید فیدبک toast داشته باشه ───
    if not data.startswith(("quiz_ans:", "ltr_ans:", "grammar_ans:", "story_ans:")):
        try:
            await query.answer()
        except Exception:
            pass

    if data in EXACT_ROUTES:
        handler = EXACT_ROUTES[data]
        if handler:
            await handler(query, context)
        return

    for prefix, handler in PREFIX_ROUTES:
        if data.startswith(prefix):
            suffix = data[len(prefix) :]
            await handler(query, context, suffix)
            return

    logger.warning("Callback ناشناخته: %s", data)
    try:
        await render(query, "⚠️ گزینه نامعتبر.", reply_markup=back_inline_keyboard())
    except BadRequest:
        if query.message:
            await query.message.reply_text(
                "⚠️ گزینه نامعتبر.", reply_markup=get_main_menu_keyboard()
            )
