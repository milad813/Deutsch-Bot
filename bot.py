import asyncio
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
from services import db, tts, run_db, get_main_menu_keyboard
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
        except Exception as e:
            logger.debug("خطا در ارسال پیام خطا به کاربر: %s", e)


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


async def daily_tts_cleanup(context):
    tts.cleanup_cache()
    logger.info("TTS cache cleanup completed")


async def daily_reminder(context):
    """Send reminder to users with due words."""
    try:
        all_users = await run_db(db.users.get_all_users)
        user_ids = [u[0] for u in all_users]
    except Exception:
        user_ids = [config.ADMIN_USER_ID] if config.ADMIN_USER_ID else []

    for uid in user_ids:
        try:
            due_count, hard_count, daily_goal, today_done = await asyncio.gather(
                run_db(db.words.get_due_count, uid),
                run_db(db.words.count_hard_due, uid),
                run_db(db.learning.get_daily_goal, uid),
                run_db(db.learning.get_today_new_words_count, uid),
            )

            if due_count > 0 or hard_count > 0:
                msg = "🔔 <b>یادآور مرور</b>\n"

                if hard_count:
                    msg += f"🔥 {hard_count} کلمه سخت معوق\n"

                if due_count:
                    msg += f"📅 {due_count} کلمه برای مرور\n"

                msg += f"🎯 امروز: {today_done}/{daily_goal}\n"

                if today_done >= daily_goal:
                    msg += "🎉 هدف امروزت کامل شده!\n"

                msg += "\nبیا تمرین کن! 💪"

                await context.bot.send_message(
                    chat_id=uid,
                    text=msg,
                    reply_markup=get_main_menu_keyboard(
                        due_count,
                        hard_count=hard_count,
                    ),
                )

                await asyncio.sleep(0.05)

        except Exception as e:
            logger.warning("خطا در ارسال یادآور به %s: %s", uid, e)

def _get_reminder_utc_time() -> datetime.time:
    """Convert configured local reminder time to UTC."""
    user_tz = datetime.timezone(
        datetime.timedelta(
            hours=config.USER_TIMEZONE_OFFSET_HOURS,
            minutes=config.USER_TIMEZONE_OFFSET_MINUTES,
        )
    )

    now_local = datetime.datetime.now(user_tz)

    target_local = now_local.replace(
        hour=config.DAILY_REMINDER_HOUR_LOCAL,
        minute=config.DAILY_REMINDER_MINUTE_LOCAL,
        second=0,
        microsecond=0,
    )

    return target_local.astimezone(datetime.timezone.utc).timetz()


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

        job_queue.run_daily(
            daily_tts_cleanup,
            time=datetime.time(hour=4, minute=0, tzinfo=datetime.timezone.utc),
            name="tts_cache_cleanup",
        )
        logger.info("TTS cache cleanup job scheduled.")

        job_queue.run_daily(
            daily_reminder,
            time=_get_reminder_utc_time(),
            name="daily_reminder",
        )
        logger.info("Daily reminder job scheduled.")

    logger.info("ربات در حال اجرا است...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
