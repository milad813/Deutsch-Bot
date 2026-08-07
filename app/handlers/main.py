"""Main command and callback handlers with authorization."""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

import app.config as config
from app.ui import main_menu_keyboard, back_inline_keyboard
from app.utils import SessionData

logger = logging.getLogger(__name__)


def get_session_data(context: ContextTypes.DEFAULT_TYPE) -> SessionData:
    """Get or create session data from context."""
    if "session_data" not in context.user_data:
        context.user_data["session_data"] = SessionData()
    return context.user_data["session_data"]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    
    # Authorization check
    if not config.settings.is_authorized_user(user.id):
        await update.message.reply_text(
            "⛔️ دسترسی ندارید. لطفاً با ادمین تماس بگیرید."
        )
        return
    
    await update.message.reply_text(
        f"👋 سلام {user.first_name}! به ربات آموزش زبان آلمانی خوش آمدید.\n\n"
        "برای شروع از منوی زیر استفاده کنید:",
        reply_markup=main_menu_keyboard(),
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /menu command."""
    user = update.effective_user
    
    # Authorization check
    if not config.settings.is_authorized_user(user.id):
        await update.message.reply_text("⛔️ دسترسی ندارید.")
        return
    
    # Clear session data
    context.user_data["session_data"] = SessionData()
    
    # Get due word counts (will be implemented with repo)
    due_count = 0  # TODO: Use word_repo.count_due(user.id)
    hard_count = 0  # TODO: Use word_repo.count_hard_due(user.id)
    
    if hard_count > 0:
        msg = f"🏠 <b>منوی اصلی</b>\n🔥 {hard_count} کلمه سخت معوق داری!"
    elif due_count > 0:
        msg = f"🏠 <b>منوی اصلی</b>\n📅 {due_count} کلمه برای مرور داری!"
    else:
        msg = "🏠 <b>منوی اصلی</b>\n🎉 همه مرورها انجام شده!"
    
    await update.message.reply_text(
        msg,
        reply_markup=main_menu_keyboard(due_count, pending=hard_count),
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all callback queries."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    # Authorization check for callbacks
    if not config.settings.is_authorized_user(user_id):
        try:
            await query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        except Exception:
            pass
        return
    
    # Acknowledge callback (except for answer-type callbacks)
    if not data.startswith(("quiz_ans:", "ltr_ans:", "grammar_ans:", "story_ans:")):
        try:
            await query.answer()
        except Exception:
            pass
    
    # Handle specific callbacks
    if data == "back_to_main_menu":
        await handle_back_to_main(query, context)
        return
    
    if data == "noop":
        return
    
    logger.debug("Callback received: %s", data)
    # TODO: Route to appropriate handler based on prefix


async def handle_back_to_main(
    query,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle back to main menu callback."""
    # Clear TTS
    session = get_session_data(context)
    session.tts_message = None
    
    # Reset session
    context.user_data["session_data"] = SessionData()
    
    # Try to delete the message
    try:
        if query.message:
            await context.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
            )
    except Exception:
        pass
    
    # Send new main menu
    user_id = query.from_user.id
    due_count = 0  # TODO: Use repo
    hard_count = 0  # TODO: Use repo
    
    if hard_count > 0:
        msg = f"🏠 <b>منوی اصلی</b>\n🔥 {hard_count} کلمه سخت معوق داری!"
    elif due_count > 0:
        msg = f"🏠 <b>منوی اصلی</b>\n📅 {due_count} کلمه برای مرور داری!"
    else:
        msg = "🏠 <b>منوی اصلی</b>\n🎉 همه مرورها انجام شده!"
    
    if query.message:
        await query.message.reply_text(
            msg,
            reply_markup=main_menu_keyboard(due_count, pending=hard_count),
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages (menu button clicks)."""
    user = update.effective_user
    
    # Authorization check
    if not config.settings.is_authorized_user(user.id):
        return
    
    text = update.message.text.strip()
    session = get_session_data(context)
    
    # Quick actions
    if text.startswith("🔥 مرور کلمات سخت"):
        # TODO: Start flashcard session with hard_only=True
        await update.message.reply_text("این قابلیت در حال توسعه است...")
        return
    
    if text.startswith("📅 مرور امروز"):
        # TODO: Start flashcard session with only_due=True
        await update.message.reply_text("این قابلیت در حال توسعه است...")
        return
    
    # Menu actions
    menu_actions = {
        "📚 کتاب و درس‌ها": "show_books",
        "🎴 فلش‌کارت": "start_flashcards",
        "🤖 کوییز": "show_quiz_menu",
        "📊 داشبورد": "show_dashboard",
        "⚙️ تنظیمات": "show_settings",
    }
    
    if text in menu_actions:
        action = menu_actions[text]
        logger.info("Menu action: %s", action)
        # TODO: Implement each action
        await update.message.reply_text(f"قابلیت '{text}' در حال توسعه است...")
        return
    
    # Unknown text - show menu again
    await update.message.reply_text(
        "لطفاً از دکمه‌های منوی زیر استفاده کنید:",
        reply_markup=main_menu_keyboard(),
    )
