import datetime
import logging

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    Defaults,
    MessageHandler,
    PicklePersistence,
    filters,
)

import config
from handlers import handle_text_input, inline_handler, show_menu, start
from services import db

config.setup_logging()
logger = logging.getLogger(__name__)


async def on_error(update, context):
    if isinstance(context.error, (BadRequest, Forbidden)):
        logger.debug("خطای قابل‌چشم‌پوشی: %s", context.error)
        return

    logger.error("خطای پیش‌بینی‌نشده در پردازش یک آپدیت", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ خطایی رخ داد. لطفاً دوباره تلاش کنید یا /menu را بزنید."
            )
        except Exception:
            pass


async def set_commands(application):
    commands = [
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "منوی اصلی"),
    ]
    await application.bot.set_my_commands(commands)


async def post_shutdown(application):
    db.close()


async def daily_backup(context):
    backup_path = db.backup()
    logger.info("بکاپ گرفته شد: %s", backup_path)


def main():
    config.validate_config()

    persistence = PicklePersistence(filepath="bot_persistence.pkl")
    defaults = Defaults(parse_mode=ParseMode.HTML)

    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .persistence(persistence)
        .defaults(defaults)
        .post_init(set_commands)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CallbackQueryHandler(inline_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input)
    )
    application.add_error_handler(on_error)

    job_queue = application.job_queue

    if job_queue:
        job_queue.run_daily(
            daily_backup,
            time=datetime.time(hour=3, minute=0, tzinfo=datetime.timezone.utc),
            name="daily_backup",
        )
        logger.info("بکاپ روزانه فعال شد.")

    logger.info("ربات در حال اجرا است...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
