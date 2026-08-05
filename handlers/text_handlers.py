import config
from services import get_main_menu_keyboard
from . import menus
from . import learning_handlers


async def handle_text_input(update, context):
    user = update.effective_user
    if not config.is_authorized_user(user.id):
        return

    text = update.message.text.strip()

    if text.startswith("🔥 مرور کلمات سخت"):
        await learning_handlers.start_flashcard_session(update, context, hard_only=True)
        return

    if text.startswith("📅 مرور امروز"):
        await learning_handlers.start_flashcard_session(update, context, only_due=True)
        return

    menu_actions = {
        "📚 کتاب و درس‌ها": lambda: menus.show_books(update, context, is_message=True),
        "🎴 فلش‌کارت": lambda: learning_handlers.start_flashcard_session(update, context),
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
