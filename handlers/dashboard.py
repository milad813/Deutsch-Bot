"""Dashboard handlers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import asyncio
import config
from models import CallbackPrefix
from core.callbacks import cb_safe
from services import db, run_db
from ui import back_inline_keyboard, esc, render


async def show_dashboard_simple(update, context):
    if hasattr(update, "effective_user") and update.effective_user:
        user_id = update.effective_user.id
    elif hasattr(update, "from_user") and update.from_user:
        user_id = update.from_user.id
    else:
        return

    if not config.is_authorized_user(user_id):
        return

    from ui import progress_bar

    # ─── آمارها ───

    (
        word_count,
        due_rows,
        quiz_stats,
        prog,
        hard,
        daily_goal,
        today_done,
        total_learned,
        total_activity,
    ) = await asyncio.gather(
        run_db(db.words.get_count),
        run_db(db.words.get_due_today, user_id),
        run_db(db.users.get_quiz_stats, user_id),
        run_db(db.users.get_progress, user_id),
        run_db(db.words.count_hard_due, user_id),
        run_db(db.learning.get_daily_goal, user_id),
        run_db(db.learning.get_today_new_words_count, user_id),
        run_db(db.learning.get_total_learned_words_count, user_id),
        run_db(db.learning.get_today_activity_count, user_id),
    )

    due_today = len(due_rows)
    correct, total = quiz_stats
    accuracy = (correct / total * 100) if total > 0 else 0
    level, into, need = db.level_from_xp(prog["xp"])

    goal_bar = progress_bar(today_done, daily_goal)
    bar = progress_bar(into, need)
    library_bar = progress_bar(total_learned, word_count)

    # ─── ساختار بخش‌بندی‌شده ───
    msg = (
        "📊 <b>داشبورد</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📈 <b>پیشرفت کلی</b>\n"
        f"   ⭐ سطح {level}  [{bar}]  {into}/{need} XP\n"
        f"   🔥 Streak: <b>{prog['streak']}</b> روز\n"
        f"   🎯 دقت: <b>{accuracy:.1f}%</b>\n"
        f"   📚 کل آموخته: <b>{total_learned}</b> از {word_count} کلمه  [{library_bar}]\n\n"
        "📅 <b>امروز</b>\n"
        f"   🎯 هدف: {today_done}/{daily_goal}  [{goal_bar}]\n"
        f"   🆕 کلمات جدید: {today_done}\n"
        f"   🔄 واژه‌های تمرین‌شده (شامل مرور): {total_activity}\n"
        f"   📋 مرور باقی‌مانده: {due_today} کلمه\n"
        f"   ⚡ مرور کلمات سخت: {hard} کلمه\n"
    )

    if today_done >= daily_goal:
        msg += "\n🎉 <b>هدف امروز کامل شد! آفرین!</b>\n"

    # ─── دکمه‌ها ───
    keyboard = []
    keyboard.append([InlineKeyboardButton("🚀 تمرین هوشمند امروز", callback_data="smart_plan")])
    if hard > 0:
        keyboard.append(
            [InlineKeyboardButton(f"🔥 مرور کلمات سخت ({hard})", callback_data="flashcard_hard")]
        )
    if due_today > 0:
        keyboard.append([InlineKeyboardButton("🚀 شروع مرور", callback_data="flashcard_due")])

    # ─── دکمه‌های جدید ───
    keyboard.append(
        [InlineKeyboardButton("📝 آزمون جامع (۲۰ سوال)", callback_data="mixed_exam:20")]
    )

    # ─── برنامه یادگیری روزانه ───
    remaining_goal = daily_goal - today_done
    if remaining_goal > 0:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📖 ادامه یادگیری ({remaining_goal} کلمه جدید)",
                    callback_data="daily_learning",
                )
            ]
        )

    keyboard.append([InlineKeyboardButton("📒 اشتباهات من", callback_data="show_error_notebook")])
    keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")])

    await render(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_error_notebook(query, context):
    """نمایش دفترچه اشتباهات حل‌نشده کاربر."""
    user_id = query.from_user.id
    items = await run_db(db.learning.get_mistake_words, user_id, limit=10)

    if not items:
        await render(
            query,
            "📒 <b>دفترچه اشتباهات</b>\n"
            "هنوز اشتباه حل‌نشده‌ای نداری! 🎉\n\n"
            "با انجام کوییز و فلش‌کارت، اشتباهاتت ذخیره می‌شوند\n"
            "و وقتی همان مهارت را درست جواب بدهی، حل می‌شوند.",
            reply_markup=back_inline_keyboard(),
        )
        return

    msg = "📒 <b>دفترچه اشتباهات حل‌نشده</b>\n"

    for item in items[:10]:
        article = (item.get("article") or "").strip()
        german = (item.get("german") or "").strip()
        display = f"{article} {german}".strip()

        msg += (
            f"🔸 <b>{esc(display)}</b> — {esc(item.get('persian') or '')}\n"
            f"❌ {item.get('wrong_count', 0)} اشتباه حل‌نشده\n"
        )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎯 تمرین اشتباهات",
                    callback_data=cb_safe(CallbackPrefix.QUIZ_SOURCE, "mistakes"),
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 داشبورد",
                    callback_data="show_dashboard",
                )
            ],
        ]
    )

    await render(query, msg, reply_markup=kb)
