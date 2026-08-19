import logging
from typing import Callable, Dict, List, Tuple

from telegram.error import BadRequest

import config
import asyncio

from handlers.admin_handlers import (
    show_admin_panel,
    show_admin_users,
    handle_reset_progress,
    handle_reset_confirm,
    handle_reset_cancel,
)
from handlers.grammar_handlers import (
    show_grammar_menu,
    show_grammar_point,
    start_grammar_quiz,
    handle_grammar_answer,
)
from handlers.listening_handlers import (
    handle_listening_start,
    handle_listening_answer,
    handle_listening_skip,
    handle_listening_exit,
    handle_listening_replay,
)
from handlers.quiz_handlers import (
    start_quiz_session,
    handle_quiz_answer,
    start_wrong_quiz,
    _send_next_quiz,
)
from handlers import menus
from handlers.learning import (
    handle_flip_card,
    handle_next_flashcard,
    handle_rate_card,
    handle_skip_flashcard,
    start_flashcard_session,
)
from handlers.learning.ltr_handlers import (
    handle_daily_learning,
    handle_ltr_answer,
    handle_ltr_exit,
    handle_ltr_learned,
    handle_ltr_ready,
    handle_ltr_review_weak,
    handle_ltr_summary,
    handle_study_lesson,
)
from handlers.story import (
    handle_story_answer,
    play_story_audio,
    play_story_listen_only,
    play_story_listen_read,
    replay_story,
    show_story,
    show_story_hint,
    show_story_menu,
    show_story_translation,
    show_story_words,
    start_story_quiz,
)
from handlers.story.quiz import handle_story_next_question
from handlers.tts_handlers import cleanup_tts, handle_speak_current
from middleware.rate_limiter import rate_limiter
from models import CallbackPrefix
from services import db, get_main_menu_keyboard, reset_session, run_db
from ui import back_inline_keyboard, render
from handlers.learning.flashcard_session import start_flashcard_due ,start_flashcard_hard

logger = logging.getLogger(__name__)

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
    await start_flashcard_session(query, context, lesson_id=lesson_id)


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
            count = await run_db(db.words.get_count_by_lesson, lesson_id)
        elif source_filter == "weak":
            count = run_db(db.words.get_weak_count,user_id)
        elif source_filter == "due":
            count = run_db(db.words.get_due_count,user_id)
        elif source_filter == "mistakes":
            count = run_db(db.learning.get_mistake_word_count,user_id)
        elif source_filter == "seen":
            count = run_db(db.words.get_seen_count,user_id)
        else:
            count = run_db(db.words.get_count)
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

    await start_quiz_session(
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
    await handle_quiz_answer(query, context)


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



async def _handle_mixed_exam(query, context, suffix: str):
    """آزمون ترکیبی سریع."""
    try:
        count = int(suffix)
    except ValueError:
        count = 20
    count = max(5, min(count, config.MAX_QUIZ_ALL_COUNT))
    await menus.start_mixed_exam(query, context, count)

async def _handle_back_to_main_menu(query, context):
    try:
        await query.answer()
    except Exception:
        pass
    await cleanup_tts(context, query.from_user.id)
    reset_session(context)

    if query.message:
        due_count, hard_count = await asyncio.gather(
            run_db(db.words.get_due_count, query.from_user.id),
            run_db(db.words.count_hard_due, query.from_user.id),
        )
        is_admin = bool(
            config.ADMIN_USER_ID and query.from_user.id == config.ADMIN_USER_ID
        )

        if hard_count > 0:
            msg = f"🏠 <b>منوی اصلی</b>\n🔥 {hard_count} کلمه سخت معوق داری!"
        elif due_count > 0:
            msg = f"🏠 <b>منوی اصلی</b>\n📅 {due_count} کلمه برای مرور داری!"
        else:
            msg = "🏠 <b>منوی اصلی</b>\n🎉 همه مرورها انجام شده!"

        # ✅ ویرایش به‌جای حذف
        try:
            await query.edit_message_text(
                msg,
                reply_markup=get_main_menu_keyboard(
                    due_count, hard_count=hard_count, is_admin=is_admin
                ),
            )
        except Exception:
            # اگر ویرایش ممکن نبود (مثلاً پیام خیلی قدیمی)
            await query.message.reply_text(
                msg,
                reply_markup=get_main_menu_keyboard(
                    due_count, hard_count=hard_count, is_admin=is_admin
                ),
            )


EXACT_ROUTES: Dict[str, Callable] = {
    "admin_panel": show_admin_panel,
    "admin_users": show_admin_users,
    "reset_progress":handle_reset_progress,
    "reset_confirm":handle_reset_confirm,
    "reset_cancel":handle_reset_cancel,
    "back_to_main_menu": None,
    "noop": None,
    "show_dashboard": menus.show_dashboard_simple,
    "show_error_notebook": menus.show_error_notebook,
    "quiz_next": _send_next_quiz,
    "show_books_inline": menus.show_books,
    "show_quiz_source": menus.show_quiz_source,
    "show_quiz_menu": menus.show_quiz_menu,
    "show_settings": menus.show_settings_menu,
    "show_level_select": menus.show_level_select,
    "show_goal_select": menus.show_goal_select,
    "quiz_retry_wrong": start_wrong_quiz,
    "next_flashcard": handle_next_flashcard,
    "ltr_ready": handle_ltr_ready,
    "ltr_learned": handle_ltr_learned,
    "ltr_summary": handle_ltr_summary,
    "ltr_exit": handle_ltr_exit,
    "flashcard_due": start_flashcard_due,
    "flashcard_hard":start_flashcard_hard,
    "daily_learning":handle_daily_learning,
    "ltr_review_weak": handle_ltr_review_weak,

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
    (CallbackPrefix.FLIP_CARD.value, handle_flip_card),
    (
        CallbackPrefix.SKIP_FLASHCARD.value,
        handle_skip_flashcard,
    ),
    (CallbackPrefix.RATE_CARD.value, handle_rate_card),
    (CallbackPrefix.SPEAK_CURRENT.value, handle_speak_current),
    (CallbackPrefix.LESSON_WORDS.value, _handle_lesson_words),
    (CallbackPrefix.BOOK.value, _handle_book),
    (CallbackPrefix.LESSON.value,menus.show_lesson_options,
    ),
    (CallbackPrefix.LTR_ANS.value,handle_ltr_answer),
    (CallbackPrefix.GRAMMAR_LESSON.value,show_grammar_menu,),
    (CallbackPrefix.GRAMMAR_POINT.value,show_grammar_point),
    (CallbackPrefix.GRAMMAR_QUIZ.value,start_grammar_quiz,),
    (CallbackPrefix.GRAMMAR_ANS.value,handle_grammar_answer,),
    (CallbackPrefix.STORY_LESSON.value,show_story_menu),
    (CallbackPrefix.STORY_VIEW.value,show_story),
    (CallbackPrefix.STORY_FA.value,show_story_translation,),
    (CallbackPrefix.STORY_WORDS.value,show_story_words),
    (CallbackPrefix.STORY_AUDIO.value,play_story_audio),
    (CallbackPrefix.STORY_HINT.value,show_story_hint),
    (CallbackPrefix.STORY_LISTEN_READ.value,play_story_listen_read,),
    (CallbackPrefix.STORY_LISTEN_ONLY.value,play_story_listen_only,),
    (CallbackPrefix.STORY_REPLAY.value,replay_story),
    (CallbackPrefix.STORY_QUIZ.value, start_story_quiz),
    (CallbackPrefix.STORY_ANS.value, handle_story_answer),
    (CallbackPrefix.STORY_NEXT_Q.value,handle_story_next_question,),
    (CallbackPrefix.STORY_NEXT.value, show_story_menu(q, c, int(s))),
    (CallbackPrefix.SET_LEVEL.value, menus.handle_set_level),
    (CallbackPrefix.SET_GOAL.value, menus.handle_set_goal),
    (
        CallbackPrefix.LISTENING_START.value,
        handle_listening_start(q, c),
    ),
    (
        CallbackPrefix.LISTENING_ANS.value,
        handle_listening_answer,
    ),
    (
        CallbackPrefix.LISTENING_SKIP.value,
        handle_listening_skip(q, c),
    ),
    (
        CallbackPrefix.LISTENING_EXIT.value,
        handle_listening_exit(q, c),
    ),
    (
        CallbackPrefix.LISTENING_REPLAY.value,
        handle_listening_replay,
    ),
    (CallbackPrefix.MIXED_EXAM.value, _handle_mixed_exam),

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
    if not data.startswith(
        ("quiz_ans:", "ltr_ans:", "grammar_ans:", "story_ans:", "listening_ans:")
    ):
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
