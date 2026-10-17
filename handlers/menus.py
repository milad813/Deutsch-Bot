from handlers.learning.lifecycle import suspend_ltr
from handlers.settings import GOALS as GOALS
from handlers.settings import LEVELS as LEVELS
from handlers.settings import handle_set_goal as handle_set_goal
from handlers.settings import handle_set_level as handle_set_level
from handlers.settings import show_goal_select as show_goal_select
from handlers.settings import show_level_select as show_level_select
from handlers.settings import show_settings_menu as show_settings_menu
from handlers.settings import toggle_reminders as toggle_reminders
from handlers.dashboard import show_dashboard_simple as show_dashboard_simple
from handlers.dashboard import show_error_notebook as show_error_notebook
from handlers.quiz_menu import show_books_for_quiz as show_books_for_quiz
from handlers.quiz_menu import show_lessons_for_quiz as show_lessons_for_quiz
from handlers.quiz_menu import show_quiz_count as show_quiz_count
from handlers.quiz_menu import show_quiz_menu as show_quiz_menu
from handlers.quiz_menu import show_quiz_source as show_quiz_source
from handlers.quiz_menu import start_mixed_exam as start_mixed_exam
from ui.text import format_lesson_name as _format_lesson_name
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from models import CallbackPrefix
import asyncio

from core.telegram_guard import should_block_non_private
from core.callbacks import cb_safe
from services import db, get_main_menu_keyboard, reset_session, run_db
from ui import _short_label, back_inline_keyboard, esc, render

ITEMS_PER_PAGE = 5


# Persian text shown to non-private chat users.
_PRIVATE_CHAT_ONLY_MESSAGE = "⛔️ لطفاً برای استفاده از ربات، به چت خصوصی مراجعه کنید."


async def _send_private_chat_only(update) -> None:
    """Send the polite Persian message via whichever reply target exists.

    The function is intentionally best-effort: if the update shape is
    unexpected (no message / no callback_query / no reply_text) we
    silently return so the guard never crashes a handler. Any exception
    raised by the underlying Telegram send is also swallowed.
    """
    try:
        message = getattr(update, "message", None) or getattr(update, "callback_query", None)
        target = getattr(message, "message", message)  # callback_query → .message
        reply_text = getattr(target, "reply_text", None)
        if reply_text is None:
            return
        await reply_text(_PRIVATE_CHAT_ONLY_MESSAGE)
    except Exception:
        # Never let a guard fail; the next authorization check will still
        # block the request.
        pass


async def _menu_stats(user_id: int):
    due, prog, hard = await asyncio.gather(
        run_db(db.words.get_due_count, user_id),
        run_db(db.users.get_progress, user_id),
        run_db(db.words.count_hard_due, user_id),
    )
    return due, prog["streak"], hard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Phase 0 hardening: non-private chats are not supported.
    if should_block_non_private(update):
        await _send_private_chat_only(update)
        return

    user = update.effective_user
    if not user:
        return
    if not config.is_authorized_user(user.id):
        await render(update, "⛔️ شما دسترسی ندارید.")
        return

    # ─── ثبت کاربر ───
    await run_db(
        db.users.register_user,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    await suspend_ltr(context)
    reset_session(context)
    # ─── Onboarding: پرسیدن سطح از کاربر جدید ───
    settings = await run_db(db.users.get_settings, user.id)
    if not settings:  # اگر رکوردی در user_settings نبود
        await show_level_select(update, context)
        return
    due, streak, hard = await _menu_stats(user.id)
    welcome = f"سلام {esc(user.first_name)} عزیز! 👋\nبه ربات یادگیری زبان آلمانی خوش آمدی! 🇩🇪\n"
    if streak > 0:
        welcome += f"🔥 streak فعلی: {streak} روز\n"
    if hard > 0:
        welcome += f"⚡ {hard} کلمه‌ی سخت معوق داری.\n"
    elif due > 0:
        welcome += f"📅 {due} کلمه برای مرور داری!\n"
    welcome += "از منوی زیر شروع کن! 🚀"
    is_admin = bool(config.ADMIN_USER_ID and user.id == config.ADMIN_USER_ID)
    await render(
        update,
        welcome,
        reply_markup=get_main_menu_keyboard(due, streak, hard, is_admin=is_admin),
    )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Phase 0 hardening: non-private chats are not supported.
    if should_block_non_private(update):
        await _send_private_chat_only(update)
        return

    user = update.effective_user
    if not user:
        return
    if not config.is_authorized_user(user.id):
        return

    # ─── ثبت کاربر ───
    await run_db(
        db.users.register_user,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    await suspend_ltr(context)
    reset_session(context)
    # ─── Onboarding: پرسیدن سطح از کاربر جدید ───
    settings = await run_db(db.users.get_settings, user.id)
    if not settings:  # اگر رکوردی در user_settings نبود
        await show_level_select(update, context)
        return
    due, streak, hard = await _menu_stats(user.id)
    msg = "🏠 <b>منوی اصلی</b>\n"
    if streak > 0:
        msg += f"🔥 streak: {streak} روز\n"
    if hard > 0:
        msg += f"⚡ {hard} کلمه‌ی سخت معوق\n"
    elif due > 0:
        msg += f"📅 {due} کلمه برای مرور داری!\n"
    else:
        msg += "🎉 همه مرورها انجام شده!\n"
    is_admin = bool(config.ADMIN_USER_ID and user.id == config.ADMIN_USER_ID)
    await render(
        update,
        msg,
        reply_markup=get_main_menu_keyboard(due, streak, hard, is_admin=is_admin),
    )


async def cancel(update, context):
    """Cancel the current in-flight operation and return to the main menu.

    Phase-0 goal: give the user a single command to bail out of any
    flashcard / quiz / LTR / story session. The handler does NOT delete
    user data — it only clears transient session state via
    :func:`reset_session` and re-shows the main menu.
    """
    user = update.effective_user if update else None
    if not user:
        return
    if not config.is_authorized_user(user.id):
        return

    # Clear transient session state (quiz, flashcards, LTR, story, etc.).
    await suspend_ltr(context)
    reset_session(context)

    # Also cancel any pending TTS auto-delete job for this user and
    # remove the audio message. ``reset_session`` only touches
    # ``user_data["tts_delete_job"]``; the module-level ``_tts_jobs`` map
    # in ``handlers.tts_handlers`` is drained per-user here.
    try:
        from handlers.tts_handlers import cleanup_tts as _cleanup_tts

        await _cleanup_tts(context, user.id)
    except Exception:
        # Never let /cancel fail on TTS bookkeeping.
        pass

    # Short confirmation + the main menu keyboard.
    message = getattr(update, "message", None)
    if message is not None:
        try:
            await message.reply_text("❌ عملیات فعلی لغو شد.")
        except Exception:
            # We never want the cancel command itself to fail.
            pass

    # Re-show the main menu so the user can pick the next action.
    await show_menu(update, context)


async def show_lessons(query, context, book_id: int):
    lessons = await run_db(db.lessons.get_by_book, book_id)
    if not lessons:
        await render(
            query,
            "📭 درسی ندارد.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙", callback_data="show_books_inline")]]
            ),
        )
        return

    user_id = query.from_user.id
    # ✅ یک کوئری برای همه درس‌ها (N+1 نمی‌شود)
    progress_map = await run_db(db.words.get_learned_counts_by_book, user_id, book_id)

    kb = []
    for lesson_id, num, title in lessons:
        p = progress_map.get(lesson_id, {"learned": 0, "total": 0})
        learned = p["learned"]
        total = p["total"]

        if total > 0:
            label = f"📝 {_format_lesson_name(num, title or '')}  ({learned}/{total})"
        else:
            label = f"📝 {_format_lesson_name(num, title or '')}"

        kb.append(
            [
                InlineKeyboardButton(
                    _short_label(label),
                    callback_data=cb_safe(CallbackPrefix.LESSON, lesson_id),
                )
            ]
        )

    kb.append([InlineKeyboardButton("🔙", callback_data="show_books_inline")])
    await render(query, "📖 یک درس انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))


async def show_books(update_or_query, context, is_message: bool = False):
    books = await run_db(db.books.get_all)
    if not books:
        text = "📭 کتابی ندارید."
        kb = [[InlineKeyboardButton("🔙", callback_data="back_to_main_menu")]]
    else:
        text = "📚 یک کتاب انتخاب کنید:"
        kb = [
            [
                InlineKeyboardButton(
                    _short_label(f"📖 {name} ({level})"),
                    callback_data=cb_safe(CallbackPrefix.BOOK, book_id),
                )
            ]
            for book_id, name, level in books
        ]
        kb.append([InlineKeyboardButton("🔙", callback_data="back_to_main_menu")])
    await render(update_or_query, text, reply_markup=InlineKeyboardMarkup(kb))


async def show_lesson_options(query, context, lesson_id: int):
    lesson = await run_db(db.lessons.get_by_id, lesson_id)
    lesson_name = _format_lesson_name(lesson[1], lesson[2] or "") if lesson else "این درس"
    book_id = await run_db(db.lessons.get_book_id, lesson_id)
    back_cb = f"book_{book_id}" if book_id else "show_books_inline"
    keyboard = [
        [
            InlineKeyboardButton(
                "📋 مشاهده لیست کلمات",
                callback_data=cb_safe(CallbackPrefix.LESSON_WORDS, f"{lesson_id}_0"),
            )
        ],
        [
            InlineKeyboardButton(
                "🧠 تمرین عمیق (LTR)", callback_data=cb_safe(CallbackPrefix.STUDY_LESSON, lesson_id)
            )
        ],
        [
            InlineKeyboardButton(
                "📖 داستان این درس", callback_data=cb_safe(CallbackPrefix.STORY_LESSON, lesson_id)
            )
        ],
        [
            InlineKeyboardButton(
                "🎴 فلش‌کارت", callback_data=cb_safe(CallbackPrefix.FLASHCARD_LESSON, lesson_id)
            )
        ],
        [
            InlineKeyboardButton(
                "🤖 کوییز", callback_data=cb_safe(CallbackPrefix.QUIZ_FROM_LESSON, lesson_id)
            )
        ],
        [
            InlineKeyboardButton(
                "📐 گرامر این درس", callback_data=cb_safe(CallbackPrefix.GRAMMAR_LESSON, lesson_id)
            )
        ],
        [InlineKeyboardButton("🔙 بازگشت به لیست درس‌ها", callback_data=back_cb)],
    ]
    await render(
        query,
        f"📚 <b>{esc(lesson_name)}</b>\nچه کاری می‌خواهی انجام بدی؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_lesson_words(query, context, lesson_id: int, page: int = 0):
    words = await run_db(db.words.get_by_lesson_full, lesson_id)
    if not words:
        await render(
            query,
            "📭 کلمه‌ای ندارد.",
            reply_markup=back_inline_keyboard("🔙 بازگشت", f"lesson_{lesson_id}"),
        )
        return
    total = len(words)
    max_page = max(0, (total - 1) // ITEMS_PER_PAGE)
    if page < 0:
        page = 0
    if page > max_page:
        page = max_page
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_words = words[start:end]

    type_emoji = {
        "Noun": "🏷️",
        "Verb": "🏃",
        "Adjective": "🎨",
        "Adverb": "➡️",
        "Preposition": "📍",
        "Pronoun": "👤",
        "Conjunction": "🔗",
        "Phrase": "💬",
        "سایر": "📌",
    }

    msg = f"📝 کلمات درس ({total} کلمه) - صفحه {page + 1}\n"
    for w in page_words:
        wtype = w.get("word_type") or "سایر"
        emoji = type_emoji.get(wtype, "📌")
        line = f"{emoji} "
        if w.get("article"):
            line += f"{esc(w['article'])} "
        line += f"<b>{esc(w['german'])}</b> — {esc(w['persian'])}"
        if w.get("english_meaning"):
            line += f"\n🇬🇧 {esc(w['english_meaning'])}"
        if w.get("plural"):
            line += f" ({esc(w['plural'])})"
        if w.get("verb_forms"):
            line += f"\n→ {esc(w['verb_forms'])}"
        if w.get("comparative"):
            line += f"\n→ {esc(w['comparative'])}"
        if w.get("collocation_de"):
            coll_de = esc(w["collocation_de"])
            coll_fa = esc(w["collocation_fa"]) if w.get("collocation_fa") else ""
            line += f"\n🔗 {coll_de}" + (f" — {coll_fa}" if coll_fa else "")
        if w.get("example_de"):
            line += f"\n📝 {esc(w['example_de'])}"
        if w.get("example_fa"):
            line += f"\n🇮🇷 <i>{esc(w['example_fa'])}</i>"
        msg += line + "\n"

    keyboard = []
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️ قبلی",
                callback_data=cb_safe(CallbackPrefix.LESSON_WORDS, f"{lesson_id}_{page - 1}"),
            )
        )
    if end < total:
        nav.append(
            InlineKeyboardButton(
                "➡️ بعدی",
                callback_data=cb_safe(CallbackPrefix.LESSON_WORDS, f"{lesson_id}_{page + 1}"),
            )
        )
    if nav:
        keyboard.append(nav)
    keyboard.append(
        [
            InlineKeyboardButton(
                "🔙 بازگشت به درس", callback_data=cb_safe(CallbackPrefix.LESSON, lesson_id)
            )
        ]
    )
    await render(query, msg, reply_markup=InlineKeyboardMarkup(keyboard))


# ─── تنظیمات سطح ───────────────────────────────────────────────


# ─── تنظیم هدف روزانه ───────────────────────────────────────────────


# ─────────────────────────────
# Error Notebook (مرحله ۳)
# ─────────────────────────────
