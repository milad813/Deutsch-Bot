import config
from core.telegram_guard import should_block_non_private
from services import get_main_menu_keyboard

from . import menus
from .learning.flashcard_session import start_flashcard_session
from .smart_plan import show_smart_plan


async def handle_text_input(update, context):
    # Phase 0 hardening: silently drop messages that originate from
    # non-private chats (groups, supergroups, channels). Unknown chat
    # types are allowed through so we don't break unusual Telegram
    # update shapes.
    if should_block_non_private(update):
        return

    user = update.effective_user
    if not config.is_authorized_user(user.id):
        return

    text = update.message.text.strip()

    if text.startswith("🔥 مرور کلمات سخت"):
        await start_flashcard_session(update, context, hard_only=True)
        return

    if text.startswith("📅 مرور امروز"):
        await start_flashcard_session(update, context, only_due=True)
        return

    if text.startswith("🛡️ پنل مدیریت"):
        if config.ADMIN_USER_ID and user.id == config.ADMIN_USER_ID:
            from handlers.admin_handlers import show_admin_panel

            await show_admin_panel(update, context)
            return

    menu_actions = {
        "🚀 تمرین هوشمند": lambda: show_smart_plan(update, context),
        "📚 کتاب و درس‌ها": lambda: menus.show_books(update, context, is_message=True),
        "🎴 فلش‌کارت": lambda: start_flashcard_session(update, context),
        "🤖 کوییز": lambda: menus.show_quiz_menu(update, context),
        "📊 داشبورد": lambda: menus.show_dashboard_simple(update, context),
        "⚙️ تنظیمات": lambda: menus.show_settings_menu(update, context),
    }

    if text in menu_actions:
        await menu_actions[text]()
        return

    await update.message.reply_text(
        "لطفاً از دکمه‌های منوی زیر استفاده کنید:",
        reply_markup=get_main_menu_keyboard(),
    )
