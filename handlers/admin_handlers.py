"""Admin panel and user management handlers."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config
from services import db
from ui import back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    """بررسی اینکه کاربر ادمین است."""
    return bool(config.ADMIN_USER_ID and user_id == config.ADMIN_USER_ID)


# ─────────────────────────────
# پنل مدیریت
# ─────────────────────────────

async def show_admin_panel(update, context):
    """پنل مدیریت - فقط برای ادمین."""
    user = getattr(update, "effective_user", None) or getattr(update, "from_user", None)
    if not user or not _is_admin(user.id):
        await render(update, "⛔️ دسترسی ندارید.", reply_markup=back_inline_keyboard())
        return

    total_users = db.get_user_count()
    active_7d = db.get_active_user_count(days=7)
    active_30d = db.get_active_user_count(days=30)
    total_words = db.get_word_count()

    msg = (
        f"🛡️ <b>پنل مدیریت</b>\n\n"
        f"👥 کل کاربران: <b>{total_users}</b>\n"
        f"🟢 فعال (۷ روز): <b>{active_7d}</b>\n"
        f"📊 فعال (۳۰ روز): <b>{active_30d}</b>\n"
        f"📚 کل کلمات کتابخانه: <b>{total_words}</b>\n"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
    ])
    await render(update, msg, reply_markup=kb)


# ─────────────────────────────
# لیست کاربران
# ─────────────────────────────

async def show_admin_users(update, context):
    """لیست کاربران با آمار - فقط برای ادمین."""
    user = getattr(update, "effective_user", None) or getattr(update, "from_user", None)
    if not user or not _is_admin(user.id):
        await render(update, "⛔️ دسترسی ندارید.", reply_markup=back_inline_keyboard())
        return

    users = db.get_all_users()
    if not users:
        await render(
            update,
            "📭 هنوز کاربری ثبت‌نام نکرده.",
            reply_markup=back_inline_keyboard("🔙 بازگشت", "admin_panel"),
        )
        return

    msg = f"👥 <b>لیست کاربران ({len(users)} نفر)</b>\n\n"

    for u in users[:20]:
        uid, username, first_name, last_name, joined, last_active = u
        name = f"{first_name or ''} {last_name or ''}".strip() or "بدون نام"
        uname = f"@{username}" if username else "بدون یوزرنیم"

        # آمار کاربر
        try:
            prog = db.get_user_progress(uid)
            correct, total = db.get_quiz_stats(uid)
            accuracy = int(correct / total * 100) if total > 0 else 0
            due = db.get_due_word_count(uid)
            weak = db.get_weak_word_count(uid)
            xp = prog.get("xp", 0)
            streak = prog.get("streak", 0)
        except Exception:
            xp, streak, accuracy, due, weak = 0, 0, 0, 0, 0

        # فرمت تاریخ عضویت
        joined_str = str(joined)[:10] if joined else "نامشخص"
        last_active_str = str(last_active)[:16] if last_active else "هرگز"

        msg += (
            f"👤 <b>{esc(name)}</b> ({esc(uname)})\n"
            f"   🆔 <code>{uid}</code>\n"
            f"   ⭐ XP: {xp} | 🔥 Streak: {streak}\n"
            f"   🎯 دقت: {accuracy}% ({correct}/{total})\n"
            f"   📅 معوق: {due} | ❌ ضعیف: {weak}\n"
            f"   📅 عضویت: {joined_str}\n"
            f"   🕐 آخرین فعالیت: {last_active_str}\n\n"
        )

    if len(users) > 20:
        msg += f"\n... و {len(users) - 20} کاربر دیگر"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_to_main_menu")],
    ])
    await render(update, msg, reply_markup=kb)


# ─────────────────────────────
# ریست پیشرفت
# ─────────────────────────────

async def handle_reset_progress(update, context):
    """مرحله ۱: نمایش پیام تأیید ریست."""
    user = getattr(update, "effective_user", None) or getattr(update, "from_user", None)
    if not user:
        return

    msg = (
        "⚠️ <b>هشدار: ریست پیشرفت</b>\n\n"
        "با این کار تمام اطلاعات زیر <b>برای همیشه</b> پاک می‌شود:\n"
        "• تمام آمار SRS و مرورها\n"
        "• تمام مهارت‌های کلمات (word skills)\n"
        "• تمام اشتباهات ثبت‌شده\n"
        "• پیشرفت داستان‌ها و گرامر\n"
        "• XP و Streak\n\n"
        "❗ این عمل <b>غیرقابل بازگشت</b> است.\n"
        "تنظیمات (سطح و هدف روزانه) حفظ می‌شود.\n\n"
        "آیا مطمئن هستید؟"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، ریست کن", callback_data="reset_confirm")],
        [InlineKeyboardButton("❌ انصراف", callback_data="reset_cancel")],
    ])
    await render(update, msg, reply_markup=kb)


async def handle_reset_confirm(update, context):
    """مرحله ۲: انجام واقعی ریست."""
    user = getattr(update, "effective_user", None) or getattr(update, "from_user", None)
    if not user:
        return

    user_id = user.id

    try:
        db.reset_user_progress(user_id)
        logger.info("پیشرفت کاربر %d ریست شد", user_id)

        msg = (
            "✅ <b>پیشرفت شما با موفقیت ریست شد.</b>\n\n"
            "همه چیز از صفر شروع می‌شود.\n"
            "تنظیمات (سطح و هدف روزانه) حفظ شده.\n\n"
            "موفق باشی! 🚀"
        )
    except Exception as e:
        logger.error("خطا در ریست پیشرفت کاربر %d: %s", user_id, e)
        msg = "❌ خطا در ریست پیشرفت. دوباره تلاش کنید."

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_to_main_menu")],
    ])
    await render(update, msg, reply_markup=kb)


async def handle_reset_cancel(update, context):
    """لغو ریست."""
    msg = "❌ ریست لغو شد. هیچ چیزی پاک نشد."
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ بازگشت به تنظیمات", callback_data="show_settings")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_to_main_menu")],
    ])
    await render(update, msg, reply_markup=kb)