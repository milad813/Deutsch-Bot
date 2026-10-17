"""Settings handlers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config
from models import CallbackPrefix
from core.callbacks import cb_safe
from services import db, run_db
from ui import back_inline_keyboard, render

LEVELS = ["A1", "A2", "B1", "B2"]


async def show_settings_menu(update, context):
    user_id = (
        update.effective_user.id
        if hasattr(update, "effective_user") and update.effective_user
        else update.from_user.id
    )
    settings = await run_db(db.users.get_settings, user_id)
    current_level = settings.get("preferred_level", "A1")
    daily_goal = settings.get("daily_goal", 10)
    reminders_enabled = settings.get("reminders_enabled", False)

    reminder_label = "🔔 یادآور: فعال" if reminders_enabled else "🔕 یادآور: غیرفعال"

    keyboard = [
        [InlineKeyboardButton(f"📐 سطح فعلی: {current_level}", callback_data="noop")],
        [InlineKeyboardButton("🔄 تغییر سطح", callback_data="show_level_select")],
        [InlineKeyboardButton(f"🎯 هدف روزانه: {daily_goal}", callback_data="show_goal_select")],
        [InlineKeyboardButton(reminder_label, callback_data="toggle_reminders")],
    ]

    # ─── فقط برای ادمین ───
    if config.ADMIN_USER_ID and user_id == config.ADMIN_USER_ID:
        keyboard.append([InlineKeyboardButton("🛡️ پنل مدیریت", callback_data="admin_panel")])

    # ─── ریست پیشرفت ───
    keyboard.append([InlineKeyboardButton("🗑️ ریست پیشرفت", callback_data="reset_progress")])

    keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")])

    await render(
        update,
        f"⚙️ <b>تنظیمات</b>\n"
        f"سطح فعلی شما: <b>{current_level}</b>\n"
        f"هدف روزانه: <b>{daily_goal}</b> کلمه",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def toggle_reminders(query, context):
    """Toggle the daily reminder opt-in flag and bounce back to settings."""
    user = query.from_user if query is not None else None
    if not user:
        return
    if not config.is_authorized_user(user.id):
        try:
            await query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        except Exception:
            pass
        return

    new_value = await run_db(db.users.toggle_reminders, user.id)
    confirmation = "✅ یادآور روزانه فعال شد." if new_value else "🔕 یادآور روزانه غیرفعال شد."

    try:
        await query.answer(confirmation, show_alert=False)
    except Exception:
        pass

    # Refresh the settings menu so the button label flips immediately.
    await show_settings_menu(query, context)


async def show_level_select(update_or_query, context):
    user_id = (
        update_or_query.effective_user.id
        if hasattr(update_or_query, "effective_user") and update_or_query.effective_user
        else update_or_query.from_user.id
    )
    settings = await run_db(db.users.get_settings, user_id)
    current_level = settings.get("preferred_level", "A1") if settings else "A1"

    keyboard = []
    for lvl in LEVELS:
        marker = "✅ " if lvl == current_level else ""
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{marker}{lvl}", callback_data=cb_safe(CallbackPrefix.SET_LEVEL, lvl)
                )
            ]
        )
    # اگر از تنظیمات آمده باشد دکمه بازگشت به تنظیمات، وگرنه منوی اصلی
    back_cb = "show_settings" if settings else "back_to_main_menu"
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb)])

    await render(
        update_or_query,
        "👋 <b>خوش آمدی!</b>\n"
        "برای اینکه داستان‌ها، مثال‌ها و کوییزها دقیقاً مناسب تو باشند،\n"
        "لطفاً <b>سطح زبان آلمانی</b> خودت را انتخاب کن:\n\n"
        "🟢 <b>A1</b> = مبتدی (کاملاً تازه‌کار)\n"
        "🟡 <b>A2</b> = متوسط (آشنایی اولیه)\n"
        "🟠 <b>B1</b> = فراتر از متوسط\n"
        "🔴 <b>B2</b> = پیشرفته",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_set_level(query, context, suffix: str):
    level = suffix.strip().upper()
    if level not in LEVELS:
        await render(query, "⚠️ سطح نامعتبر.", reply_markup=back_inline_keyboard())
        return
    user_id = query.from_user.id
    await run_db(db.users.update_setting, user_id, level)
    await render(
        query,
        f"✅ سطح شما به <b>{level}</b> تغییر کرد!\n"
        "از الان مثال‌ها و داستان‌ها با این سطح ساخته می‌شوند.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⚙️ تنظیمات", callback_data="show_settings")],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
            ]
        ),
    )


GOALS = [5, 10, 15, 20, 30, 50]


async def show_goal_select(query, context):
    user_id = query.from_user.id
    settings = await run_db(db.users.get_settings, user_id)
    current_goal = settings.get("daily_goal", 10)

    keyboard = []
    for goal in GOALS:
        marker = "✅ " if goal == current_goal else ""
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{marker}{goal} کلمه", callback_data=cb_safe(CallbackPrefix.SET_GOAL, goal)
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="show_settings")])
    await render(
        query,
        "🎯 <b>هدف روزانه خود را انتخاب کنید:</b>\nتعداد کلماتی که هر روز تمرین می‌کنید.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_set_goal(query, context, suffix: str):
    try:
        goal = int(suffix.strip())
        if goal not in GOALS:
            raise ValueError()
    except (ValueError, TypeError):
        await render(query, "⚠️ هدف نامعتبر.", reply_markup=back_inline_keyboard())
        return
    user_id = query.from_user.id
    await run_db(db.learning.set_daily_goal, user_id, goal)
    await render(
        query,
        f"✅ هدف روزانه شما به <b>{goal}</b> کلمه تغییر کرد!\n"
        "هر روز این تعداد کلمه را تمرین کن تا پیشرفت کنی.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⚙️ تنظیمات", callback_data="show_settings")],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
            ]
        ),
    )
