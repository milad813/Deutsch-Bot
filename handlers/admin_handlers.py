"""Admin panel and user management handlers."""

import logging
import os
import re
from typing import List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import asyncio

import config
from services import db, llm, run_db
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

    total_users, active_7d, active_30d, total_words = await asyncio.gather(
        run_db(db.users.get_user_count),
        run_db(db.users.get_active_user_count, 7),
        run_db(db.users.get_active_user_count, 30),
        run_db(db.words.get_count),
)

    msg = (
        f"🛡️ <b>پنل مدیریت</b>\n\n"
        f"👥 کل کاربران: <b>{total_users}</b>\n"
        f"🟢 فعال (۷ روز): <b>{active_7d}</b>\n"
        f"📊 فعال (۳۰ روز): <b>{active_30d}</b>\n"
        f"📚 کل کلمات کتابخانه: <b>{total_words}</b>\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👥 لیست کاربران", callback_data="admin_users")],
            [InlineKeyboardButton("📊 وضعیت سیستم", callback_data="admin_status")],
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
        ]
    )
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

    users = await run_db(db.users.get_all_users)
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
        correct, total = 0, 0
        try:
            prog = await run_db(db.users.get_progress, uid)
            correct, total = await run_db(db.users.get_quiz_stats, uid)
            due = await run_db(db.words.get_due_count, uid)
            weak = await run_db(db.words.get_weak_count, uid)
            xp = prog.get("xp", 0)
            streak = prog.get("streak", 0)
            accuracy = round(correct / total * 100) if total else 0
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

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_to_main_menu")],
        ]
    )
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

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ بله، ریست کن", callback_data="reset_confirm")],
            [InlineKeyboardButton("❌ انصراف", callback_data="reset_cancel")],
        ]
    )
    await render(update, msg, reply_markup=kb)


async def handle_reset_confirm(update, context):
    """مرحله ۲: انجام واقعی ریست."""
    user = getattr(update, "effective_user", None) or getattr(update, "from_user", None)
    if not user:
        return

    user_id = user.id

    try:
        await run_db(db.users.reset_user_progress, user_id)
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

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_to_main_menu")],
        ]
    )
    await render(update, msg, reply_markup=kb)


async def handle_reset_cancel(update, context):
    """لغو ریست."""
    msg = "❌ ریست لغو شد. هیچ چیزی پاک نشد."
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚙️ بازگشت به تنظیمات", callback_data="show_settings"
                )
            ],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_to_main_menu")],
        ]
    )
    await render(update, msg, reply_markup=kb)



# ─────────────────────────────
# /status — Operational monitoring
# ─────────────────────────────

# Story-generation job names are registered in
# ``handlers/story/jobs.py`` as ``"story_gen_<user_id>"``.  Any other
# job registered by the bot (e.g. ``daily_backup``, ``daily_reminder``)
# is operational bookkeeping, not an in-flight user story, so we filter
# by this prefix when reporting "active story jobs".
_STORY_JOB_NAME_PREFIX = "story_gen_"


def _bot_mode_label() -> str:
    """Return a human-readable Persian label for ``config.BOT_MODE``.

    Falls back to the raw enum value so a future ``BotMode`` member
    cannot break the admin view.
    """
    mode = getattr(config, "BOT_MODE", None)
    value = getattr(mode, "value", None) or str(mode) or "unknown"
    persian = {
        "online": "آنلاین (همیشه LLM)",
        "offline": "آفلاین (بدون LLM)",
        "hybrid": "هیبرید (پیش‌فرض)",
    }
    return persian.get(value, value)


def _groq_key_count() -> int:
    """Number of configured Groq API keys, **without** revealing them.

    Returns 0 if no key is configured so the admin can immediately see
    when the LLM is silently downgraded to offline.
    """
    keys = getattr(config, "GROQ_API_KEYS", None) or []
    return len(keys)


def _llm_available() -> bool:
    """Best-effort LLM availability check, never raises.

    We trust ``llm.is_available()`` (the service-level check) but fall
    back to ``config.is_llm_available()`` if the service object is
    missing or the method raises — the admin view must not crash on
    a misconfigured LLM module.
    """
    try:
        if hasattr(llm, "is_available"):
            result = llm.is_available()
            if isinstance(result, bool):
                return result
    except Exception:
        pass
    try:
        return bool(config.is_llm_available())
    except Exception:
        return False


def _active_story_jobs(context):
    """Return ``(count, names)`` of active story-generation jobs.

    We read ``context.job_queue.jobs()`` (the PTB API for the currently
    scheduled jobs).  Names are filtered to the ``story_gen_`` prefix
    and sorted for stable rendering.
    """
    job_queue = getattr(context, "job_queue", None) if context else None
    if job_queue is None:
        return 0, []
    try:
        jobs = job_queue.jobs() or ()
    except Exception:
        return 0, []
    names = sorted(
        str(getattr(j, "name", "") or "")
        for j in jobs
        if str(getattr(j, "name", "") or "").startswith(_STORY_JOB_NAME_PREFIX)
    )
    return len(names), names


_PHASE1_ITEM_RE = re.compile(r"-\s*\[(?P<mark>[ xX])\]\s*(?P<text>.+)")


def _phase1_status(repo_root=None):
    """Return ``(done, total, outstanding)`` parsed from ``docs/PHASE1.md``.

    Tolerant parser: any ``- [x]`` / ``- [X]`` counts as done, ``- [ ]``
    as outstanding.  Lines that don't match the checklist shape are
    ignored so the section prose (e.g. "Goal: …") never inflates the
    counter.

    Returns ``(0, 0, [])`` if the file is missing or unreadable so the
    admin page still renders on a fresh checkout.
    """
    if repo_root is None:
        repo_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    path = os.path.join(repo_root, "docs", "PHASE1.md")
    if not os.path.exists(path):
        return 0, 0, []
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return 0, 0, []
    done = 0
    total = 0
    outstanding = []
    for line in text.splitlines():
        m = _PHASE1_ITEM_RE.search(line)
        if not m:
            continue
        total += 1
        if m.group("mark").lower() == "x":
            done += 1
        else:
            outstanding.append(m.group("text").strip())
    return done, total, outstanding


async def show_status(update, context):
    """Admin ``/status`` — operational monitoring view.

    Surfaces (in Persian):

    * ``BOT_MODE`` + LLM availability + Groq key count (no secrets).
    * Database path + library totals (words/books/lessons).
    * User funnel (total / 7d / 30d).
    * Reminder opt-in count.
    * Today's LLM usage totals (if ``user_llm_usage`` exists).
    * Active story-generation jobs (if ``job_queue`` is reachable).
    * Phase 1 checklist progress (if ``docs/PHASE1.md`` exists).

    Non-admins get a one-line "no access" notice and the function
    returns; no data is fetched for them, so a non-admin can never
    trigger the expensive aggregation queries.
    """
    user = getattr(update, "effective_user", None) or getattr(
        update, "from_user", None
    )
    if user is None:
        # When the handler is invoked via the callback router
        # (``EXACT_ROUTES["admin_status"]``), the first arg is a
        # ``CallbackQuery`` whose user lives on ``.from_user`` and
        # whose message is on ``.message``.  Fall back to those so
        # the same handler works for both the ``/status`` command
        # and the admin-panel inline button.
        callback = getattr(update, "callback_query", None)
        if callback is not None:
            user = getattr(callback, "from_user", None)
        else:
            user = getattr(update, "from_user", None)
    if not user or not _is_admin(user.id):
        await render(update, "⛔️ دسترسی ندارید.", reply_markup=back_inline_keyboard())
        return

    # Pull the cheap / independent counters in parallel so the page
    # renders in one DB round-trip's worth of latency.
    (
        total_users,
        active_7d,
        active_30d,
        total_words,
        total_books,
        total_lessons,
        reminder_ids,
        llm_totals,
    ) = await asyncio.gather(
        run_db(db.users.get_user_count),
        run_db(db.users.get_active_user_count, 7),
        run_db(db.users.get_active_user_count, 30),
        run_db(db.words.get_count),
        run_db(db.books.get_count),
        run_db(db.lessons.get_count),
        run_db(db.users.get_reminder_user_ids),
        run_db(db.learning.get_llm_usage_totals_today),
        return_exceptions=False,
    )

    story_job_count, story_job_names = _active_story_jobs(context)
    done, total_items, outstanding = _phase1_status()

    llm_ok = _llm_available()
    groq_keys = _groq_key_count()

    # ── format the status body ─────────────────────────────────────
    lines = ["📊 <b>وضعیت سیستم</b>\n"]

    lines.append("⚙️ <b>پیکربندی</b>")
    lines.append(f"   • حالت ربات: <b>{esc(_bot_mode_label())}</b>")
    lines.append(
        f"   • LLM در دسترس: <b>{'بله ✅' if llm_ok else 'خیر ❌'}</b>"
    )
    lines.append(f"   • تعداد کلیدهای Groq: <b>{groq_keys}</b>")
    lines.append(f"   • مسیر دیتابیس: <code>{esc(config.DB_PATH)}</code>\n")

    lines.append("📚 <b>محتوا</b>")
    lines.append(f"   • کل کلمات: <b>{total_words}</b>")
    lines.append(f"   • کل کتاب‌ها: <b>{total_books}</b>")
    lines.append(f"   • کل درس‌ها: <b>{total_lessons}</b>\n")

    lines.append("👥 <b>کاربران</b>")
    lines.append(f"   • کل کاربران: <b>{total_users}</b>")
    lines.append(f"   • فعال ۷ روز اخیر: <b>{active_7d}</b>")
    lines.append(f"   • فعال ۳۰ روز اخیر: <b>{active_30d}</b>")
    lines.append(f"   • یادآور روزانه فعال: <b>{len(reminder_ids)}</b>\n")

    lines.append("🤖 <b>مصرف LLM (امروز)</b>")
    lines.append(f"   • داستان: <b>{llm_totals['story']}</b>")
    lines.append(f"   • مثال: <b>{llm_totals['example']}</b>\n")

    lines.append("⏳ <b>صف تولید داستان</b>")
    if story_job_count == 0:
        lines.append("   • داستان فعال: <b>۰</b>\n")
    else:
        lines.append(f"   • داستان فعال: <b>{story_job_count}</b>")
        for name in story_job_names:
            lines.append(f"      - <code>{esc(name)}</code>")
        lines.append("")

    lines.append("🗂️ <b>وضعیت Phase 1</b>")
    if total_items == 0:
        lines.append("   • فایل <code>docs/PHASE1.md</code> یافت نشد.\n")
    else:
        lines.append(
            f"   • تکمیل‌شده: <b>{done}/{total_items}</b>"
        )
        if outstanding:
            shown = outstanding[:5]
            for item in shown:
                lines.append(f"      - ⏳ {esc(item)}")
            if len(outstanding) > len(shown):
                lines.append(
                    f"      - … و {len(outstanding) - len(shown)} مورد دیگر"
                )
        lines.append("")

    msg = "\n".join(lines).rstrip()

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_to_main_menu")],
        ]
    )
    await render(update, msg, reply_markup=kb)
