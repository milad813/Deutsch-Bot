import asyncio
import datetime
import logging

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter
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
from core.logging_utils import log_event
from handlers import handle_text_input, inline_handler, show_menu, start
from handlers.admin_handlers import show_status
from handlers.menus import cancel
from middleware.rate_limiter import rate_limiter
from services import app, db, get_main_menu_keyboard, run_db, tts
config.setup_logging()
logger = logging.getLogger(__name__)


async def on_error(update, context):
    # Phase 0: if a callback query triggered the error, always try to
    # answer it with a short Persian notice. This stops Telegram's
    # "loading…" spinner on the user's screen, even for BadRequest /
    # Forbidden errors that we would otherwise silently ignore.
    if isinstance(update, Update) and update.callback_query is not None:
        try:
            await update.callback_query.answer("⚠️ خطایی رخ داد.")
        except Exception:
            # Never let the error handler itself crash the dispatcher.
            pass

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
        BotCommand("cancel", "لغو عملیات فعلی"),
        BotCommand("status", "وضعیت سیستم"),
    ]
    await application.bot.set_my_commands(commands)


async def post_shutdown(application):
    # Phase 0: cancel any pending TTS auto-delete jobs and drop the
    # in-memory ``_tts_jobs`` map so it doesn't survive the process.
    # Without this, a long-running instance leaks one entry per TTS play.
    try:
        from handlers.tts_handlers import cleanup_all_tts_jobs
        cleanup_all_tts_jobs()
    except Exception as e:
        logger.debug("TTS shutdown cleanup skipped: %s", e)
    app.close()


async def daily_backup(context):
    backup_path = await run_db(db.backup)
    logger.info("بکاپ گرفته شد: %s", backup_path)


async def daily_tts_cleanup(context):
    await asyncio.to_thread(tts.cleanup_cache)
    # Drop bookkeeping for users who haven't pinged us in a full window,
    # so the in-memory rate-limit dict doesn't grow forever.
    rate_limiter.cleanup()
    logger.info("TTS cache cleanup completed")


async def daily_reminder(context):
    """Send reminder to users with due words.

    Hardening history:

    * **Phase 0** -- only pings users who explicitly opted in via
      ``user_settings.reminders_enabled`` AND were active in the last
      30 days.  Re-checks ``config.is_authorized_user`` inside the
      loop so stale rows in the DB (e.g. after rotating
      ``ADMIN_USER_ID``) can never result in a message to an
      unauthorized chat.

    * **Phase 1 (this revision)** -- turns the loop into a batched,
      flood-aware job:

      1. The recipient list is sliced into chunks of
         ``config.REMINDER_BATCH_SIZE`` (default 50) so the worst-case
         number of DB round-trips per run is
         ``4 * ceil(N / REMINDER_BATCH_SIZE)`` instead of ``4 * N``.
      2. Each batch issues ONE ``GROUP BY`` query per stat
         (due / hard / goal / today-new) instead of four per user.
      3. A user is only sent a reminder if ``due_count > 0`` or
         ``hard_count > 0``; users with nothing to do are silently
         skipped (no chat message, no quota impact).
      4. Telegram ``RetryAfter`` (flood control) is caught and the
         job sleeps the exact number of seconds Telegram asked for
         before continuing.
      5. ``Forbidden`` / ``BadRequest`` (bot blocked by user, chat
         gone, etc.) are caught per user, logged, and the loop moves
         on -- one bad recipient must not abort the whole run.
      6. ``config.REMINDER_SLEEP_SECONDS`` (default 1.0) is slept
         between batches so we never burst more than one batch per
         second at Telegram.
    """
    try:
        user_ids = await run_db(db.users.get_reminder_user_ids)
    except Exception:
        user_ids = [config.ADMIN_USER_ID] if config.ADMIN_USER_ID else []

    if not user_ids:
        logger.info("یادآور روزانه: هیچ کاربر فعال و فعال‌سازی‌شده‌ای پیدا نشد.")
        return

    batch_size = max(1, int(getattr(config, "REMINDER_BATCH_SIZE", 50) or 50))
    inter_batch_sleep = float(
        getattr(config, "REMINDER_SLEEP_SECONDS", 1.0) or 1.0
    )
    logger.info(
        "یادآور روزانه: ارسال به %d کاربر در دسته‌های %d‌تایی.",
        len(user_ids),
        batch_size,
    )
    log_event(
        logger,
        logging.INFO,
        "reminder_batch_started",
        recipient_count=len(user_ids),
        batch_size=batch_size,
        inter_batch_sleep_seconds=inter_batch_sleep,
    )

    sent_count = 0
    skip_count = 0
    error_count = 0

    # Walk the recipients in fixed-size chunks.  The first batch is
    # processed immediately; subsequent batches sleep a configurable
    # pause first so the bot never bursts >REMINDER_BATCH_SIZE
    # messages per ``REMINDER_SLEEP_SECONDS`` seconds at Telegram.
    for batch_index, start in enumerate(range(0, len(user_ids), batch_size)):
        batch = user_ids[start : start + batch_size]
        if batch_index > 0:
            await asyncio.sleep(inter_batch_sleep)

        # 1) Pull every per-user stat for the batch in 4 round-trips.
        try:
            due_map, hard_map, goal_map, today_map = await asyncio.gather(
                run_db(db.users.get_due_counts_for_users, batch),
                run_db(db.users.get_hard_due_counts_for_users, batch),
                run_db(db.users.get_daily_goals_for_users, batch),
                run_db(db.users.get_today_new_counts_for_users, batch),
            )
        except Exception as e:
            logger.error(
                "خطا در واکشی آمار یادآور برای دسته %s: %s", batch, e
            )
            error_count += len(batch)
            continue

        # 2) Send a reminder to every user in the batch that has
        #    something to do.  We intentionally *do not* short-circuit
        #    on a single user failure -- a blocked / deactivated user
        #    must not poison the rest of the batch.
        for uid in batch:
            if not config.is_authorized_user(uid):
                skip_count += 1
                continue

            due_count = int(due_map.get(uid, 0))
            hard_count = int(hard_map.get(uid, 0))
            # ``get_daily_goals_for_users`` defaults to 10 for users
            # with no settings row, so ``goal_map.get`` is safe.
            daily_goal = int(goal_map.get(uid, 10))
            today_done = int(today_map.get(uid, 0))

            if due_count <= 0 and hard_count <= 0:
                # Nothing to do today -- skip silently.
                skip_count += 1
                continue

            msg = "🔔 <b>یادآور مرور</b>\n"

            if hard_count:
                msg += f"🔥 {hard_count} کلمه سخت معوق\n"

            if due_count:
                msg += f"📅 {due_count} کلمه برای مرور\n"

            msg += f"🎯 امروز: {today_done}/{daily_goal}\n"

            if today_done >= daily_goal:
                msg += "🎉 هدف امروزت کامل شده!\n"

            msg += "\nبیا تمرین کن! 💪"

            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=msg,
                    reply_markup=get_main_menu_keyboard(
                        due_count,
                        hard_count=hard_count,
                    ),
                )
                sent_count += 1
            except RetryAfter as e:
                # Telegram told us to back off.  Sleep the exact
                # number of seconds it asked for (plus a tiny safety
                # margin so the next request is comfortably past the
                # retry window) and then continue the batch -- a
                # single flood-hit must not abort the whole run.
                wait = int(getattr(e, "retry_after", 1) or 1) + 1
                logger.warning(
                    "Telegram flood control: توقف %d ثانیه پس از ارسال به %s.",
                    wait,
                    uid,
                )
                await asyncio.sleep(wait)
                # Skip the sleep-once-per-user micro-delay; we just
                # slept a real amount.
            except (Forbidden, BadRequest) as e:
                # User blocked the bot, chat was deleted, etc.  Log
                # and move on -- retrying never helps.
                error_count += 1
                log_event(
                    logger,
                    logging.WARNING,
                    "reminder_send_failed",
                    user_id=uid,
                    error_type=type(e).__name__,
                    reason="forbidden_or_bad_request",
                )
                logger.info(
                    "ارسال یادآور به %s ناموفق بود (غیرقابل بازیابی): %s",
                    uid,
                    e,
                )
            except Exception as e:
                # Network glitch, etc.  Log and continue.
                error_count += 1
                log_event(
                    logger,
                    logging.WARNING,
                    "reminder_send_failed",
                    user_id=uid,
                    error_type=type(e).__name__,
                    reason="transient",
                )
                logger.warning("خطا در ارسال یادآور به %s: %s", uid, e)

            # Tiny per-user pause so a 50-user batch never bursts
            # 50 messages in the same millisecond at PTB.  A
            # RetryAfter handler already absorbed the bulk of any
            # back-off; this just smooths the tail.
            await asyncio.sleep(0.05)

    log_event(
        logger,
        logging.INFO,
        "reminder_batch_finished",
        recipient_count=len(user_ids),
        sent_count=sent_count,
        skip_count=skip_count,
        error_count=error_count,
        batch_size=batch_size,
    )


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
    # Single shared service container (see services/container.py).
    application.bot_data["app"] = app

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("status", show_status))
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
