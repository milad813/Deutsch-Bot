import logging
from typing import Callable, Dict, List, Tuple

from telegram.error import BadRequest

import config
# ✅ جایگزین:
from handlers import grammar_handlers, menus, quiz_handlers, admin_handlers
from handlers.learning.ltr_handlers import (
    handle_study_lesson, handle_ltr_ready, handle_ltr_summary,
    handle_ltr_exit, handle_ltr_answer
)
from handlers.story import (
    show_story_menu,
    show_story,
    show_story_translation,
    show_story_words,
    play_story_audio,
    show_story_hint,
    play_story_listen_read,
    play_story_listen_only,
    replay_story,
    start_story_quiz,
    handle_story_answer,
)
from handlers.learning import (FlashcardSessionManager, handle_flip_card,
                               handle_next_flashcard, handle_rate_card,
                               handle_skip_flashcard, start_flashcard_session)
from handlers.learning.ltr_session import LTRSessionManager
from middleware.rate_limiter import rate_limiter
from models import CallbackPrefix
from services import db, get_main_menu_keyboard, reset_session, tts
from ui import back_inline_keyboard, render
from handlers import writing_handlers, listening_handlers
from handlers.tts_handlers import cleanup_tts, send_ephemeral_audio, handle_speak_current

logger = logging.getLogger(__name__)

_tts_jobs: Dict[int, object] = {}


async def _handle_quiz_type(query, context, suffix: str):
    context.user_data["quiz_type"] = suffix
    if context.user_data.get("quiz_lesson_preset"):
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
    await start_flashcard_session(query, context, lesson_id=lesson_id)  # ✅ مستقیم


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
    elif suffix == "mistakes":
        context.user_data.pop("quiz_lesson_id", None)
        context.user_data["quiz_source_filter"] = "mistakes"
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
        elif source_filter == "mistakes":
            count = db.get_mistake_word_count(user_id)
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
    
    # پاک کردن quiz_lesson_preset قبل از شروع session
    context.user_data.pop("quiz_lesson_preset", None)
    
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
    try:
        await query.answer()
    except Exception:
        pass

    await cleanup_tts(context, query.from_user.id)  # ✅
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

        # ─── بررسی ادمین ───
        is_admin = bool(
            config.ADMIN_USER_ID and query.from_user.id == config.ADMIN_USER_ID
        )

        if hard_count > 0:
            msg = f"🏠 <b>منوی اصلی</b>\n🔥 {hard_count} کلمه سخت معوق داری!"
        elif due_count > 0:
            msg = f"🏠 <b>منوی اصلی</b>\n📅 {due_count} کلمه برای مرور داری!"
        else:
            msg = "🏠 <b>منوی اصلی</b>\n🎉 همه مرورها انجام شده!"

        await query.message.reply_text(
            msg,
            reply_markup=get_main_menu_keyboard(
                due_count, hard_count=hard_count, is_admin=is_admin
            ),
        )

EXACT_ROUTES: Dict[str, Callable] = {
    "admin_panel": admin_handlers.show_admin_panel,
    "admin_users": lambda q, c: admin_handlers.show_admin_users(q, c),
    "reset_progress": lambda q, c: admin_handlers.handle_reset_progress(q, c),
    "reset_confirm": lambda q, c: admin_handlers.handle_reset_confirm(q, c),
    "reset_cancel": lambda q, c: admin_handlers.handle_reset_cancel(q, c),
    "back_to_main_menu": None,
    "noop": None,
    "show_dashboard": lambda q, c: menus.show_dashboard_simple(q, c),
    "show_error_notebook": lambda q, c: menus.show_error_notebook(q, c),
    "quiz_next": quiz_handlers._send_next_quiz,
    "show_books_inline": lambda q, c: menus.show_books(q, c, is_message=False),
    "show_quiz_source": lambda q, c: menus.show_quiz_source(q, c),
    "show_quiz_menu": lambda q, c: menus.show_quiz_menu(q, c),
    "show_settings": lambda q, c: menus.show_settings_menu(q, c),
    "show_level_select": lambda q, c: menus.show_level_select(q, c),
    "show_goal_select": lambda q, c: menus.show_goal_select(q, c),
    "quiz_retry_wrong": lambda q, c: quiz_handlers.start_wrong_quiz(q, c),
    "next_flashcard": lambda q, c: handle_next_flashcard(q, c),
    "ltr_ready": handle_ltr_ready,
    "ltr_summary": handle_ltr_summary,
    "ltr_exit": handle_ltr_exit,
    "next_flashcard": handle_next_flashcard,
    "flashcard_due": lambda q, c: start_flashcard_session(q, c, only_due=True),
    "flashcard_hard": lambda q, c: start_flashcard_session(q, c, hard_only=True),
    "ltr_summary": lambda q, c: handle_ltr_summary(q, c),
    "ltr_exit": lambda q, c: handle_ltr_exit(q, c),
    "flashcard_due": lambda q, c: start_flashcard_session(
        q, c, only_due=True
    ),
    "flashcard_hard": lambda q, c: start_flashcard_session(
        q, c, hard_only=True
    ),
}

# Type-safe callback routing using CallbackPrefix enum
PREFIX_ROUTES: List[Tuple[str, Callable]] = [
    (CallbackPrefix.QUIZ_TYPE.value, _handle_quiz_type),
    (CallbackPrefix.QUIZ_SOURCE.value, _handle_quiz_source),
    (CallbackPrefix.QUIZ_COUNT.value, _handle_quiz_count),
    (CallbackPrefix.QUIZ_BOOK.value, _handle_quiz_book),
    (CallbackPrefix.QUIZ_LESSON.value, _handle_quiz_lesson),
    (CallbackPrefix.QUIZ_ANS.value, _handle_quiz_ans),
    (CallbackPrefix.QUIZ_FROM_LESSON.value, _handle_quiz_from_lesson),
    (CallbackPrefix.FLASHCARD_LESSON.value, _handle_flashcard_lesson),
    (CallbackPrefix.STUDY_LESSON.value, handle_study_lesson),
    (CallbackPrefix.FLIP_CARD.value, lambda q, c, s: handle_flip_card(q, c, s)),
    (
        CallbackPrefix.SKIP_FLASHCARD.value,
        lambda q, c, s: handle_skip_flashcard(q, c, s),
    ),
    (CallbackPrefix.RATE_CARD.value, lambda q, c, s: handle_rate_card(q, c, s)),
    (CallbackPrefix.SPEAK_CURRENT.value, handle_speak_current),
    (CallbackPrefix.LESSON_WORDS.value, _handle_lesson_words),
    (CallbackPrefix.BOOK.value, _handle_book),
    (CallbackPrefix.LESSON.value, lambda q, c, s: menus.show_lesson_options(q, c, int(s))),
    (CallbackPrefix.LTR_ANS.value, lambda q, c, s: handle_ltr_answer(q, c, s)),
    (
        CallbackPrefix.GRAMMAR_LESSON.value,
        lambda q, c, s: grammar_handlers.show_grammar_menu(q, c, int(s)),
    ),
    (
        CallbackPrefix.GRAMMAR_POINT.value,
        lambda q, c, s: grammar_handlers.show_grammar_point(q, c, int(s)),
    ),
    (
        CallbackPrefix.GRAMMAR_QUIZ.value,
        lambda q, c, s: grammar_handlers.start_grammar_quiz(q, c, int(s)),
    ),
    (CallbackPrefix.GRAMMAR_ANS.value, lambda q, c, s: grammar_handlers.handle_grammar_answer(q, c, s)),
    (CallbackPrefix.STORY_LESSON.value, lambda q, c, s: show_story_menu(q, c, int(s))),
    (CallbackPrefix.STORY_VIEW.value, lambda q, c, s: show_story(q, c, int(s))),
    (CallbackPrefix.STORY_FA.value, lambda q, c, s: show_story_translation(q, c, int(s))),
    (CallbackPrefix.STORY_WORDS.value, lambda q, c, s: show_story_words(q, c, int(s))),
    (CallbackPrefix.STORY_AUDIO.value, lambda q, c, s: play_story_audio(q, c, int(s))),
    (CallbackPrefix.STORY_HINT.value, lambda q, c, s: show_story_hint(q, c, int(s))),
    (CallbackPrefix.STORY_LISTEN_READ.value, lambda q, c, s: play_story_listen_read(q, c, int(s))),
    (CallbackPrefix.STORY_LISTEN_ONLY.value, lambda q, c, s: play_story_listen_only(q, c, int(s))),
    (CallbackPrefix.STORY_REPLAY.value, lambda q, c, s: replay_story(q, c, int(s))),
    (CallbackPrefix.STORY_QUIZ.value, lambda q, c, s: start_story_quiz(q, c, int(s))),
    (CallbackPrefix.STORY_ANS.value, lambda q, c, s: handle_story_answer(q, c, s)),
    (CallbackPrefix.STORY_NEXT.value, lambda q, c, s: show_story_menu(q, c, int(s))),
    (CallbackPrefix.SET_LEVEL.value, lambda q, c, s: menus.handle_set_level(q, c, s)),
    (CallbackPrefix.SET_GOAL.value, lambda q, c, s: menus.handle_set_goal(q, c, s)),
    (CallbackPrefix.WRITING_START.value, lambda q, c, s: writing_handlers.handle_writing_start(q, c)),
    (CallbackPrefix.WRITING_SKIP.value, lambda q, c, s: writing_handlers.handle_writing_skip(q, c)),
    (CallbackPrefix.WRITING_EXIT.value, lambda q, c, s: writing_handlers.handle_writing_exit(q, c)),
    (CallbackPrefix.LISTENING_START.value, lambda q, c, s: listening_handlers.handle_listening_start(q, c)),
    (CallbackPrefix.LISTENING_ANS.value, lambda q, c, s: listening_handlers.handle_listening_answer(q, c, s)),
    (CallbackPrefix.LISTENING_SKIP.value, lambda q, c, s: listening_handlers.handle_listening_skip(q, c)),
    (CallbackPrefix.LISTENING_EXIT.value, lambda q, c, s: listening_handlers.handle_listening_exit(q, c)),
    (CallbackPrefix.LISTENING_REPLAY.value, lambda q, c, s: listening_handlers.handle_listening_replay(q, c, s)),
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

    # Rate limiting
    if not rate_limiter.is_allowed(query.from_user.id):
        try:
            await query.answer("⏳ لطفاً کمی صبر کنید.", show_alert=True)
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
    if not data.startswith(("quiz_ans:", "ltr_ans:", "grammar_ans:")):
        try:
            await query.answer()
        except Exception:
            pass
    # story_ans فیدبک را در handler خودش می‌دهد

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
