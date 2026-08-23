"""«تمرین هوشمند» — برنامه‌ی روزانه‌ی تطبیقی برای حلقه‌ی یادگیری.

یک صفحه‌ی واحد که با نگاه به وضعیت واقعی کاربر (مرورهای معوق FSRS،
کلمات سخت lapse شده، اشتباهات حل‌نشده و هدف روزانه) یک برنامه‌ی
اولویت‌دار می‌سازد و برای هر مرحله دکمه‌ی اجرای همان موتورهای موجود
(فلش‌کارت / کوییز اشتباهات / LTR جدید) را ارائه می‌دهد.

اولویت‌بندی بر اساس اصول علم یادگیری:
    ۱. کلمات سخت معوق  → بیشترین ریسک فراموشی (lapse شده‌اند)
    ۲. مرورهای سرسید    → نگه‌داشتن retrievability بالای آستانه
    ۳. اشتباهات باز      → ترمیم فعال قبل از ورودی جدید
    ۴. کلمات جدید        → رشد؛ فقط بعد از تثبیت مطالب قبلی

این ماژول هیچ state جدیدی به user_data اضافه نمی‌کند.
"""

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from models import CallbackPrefix
from services import db, run_db
from ui import progress_bar, render

logger = logging.getLogger(__name__)


async def _gather_daily_state(user_id: int) -> dict:
    """وضعیت امروز کاربر را با یک batch موازی از دیتابیس جمع می‌کند."""
    (
        hard_count,
        due_count,
        mistake_count,
        daily_goal,
        today_done,
        progress,
    ) = await asyncio.gather(
        run_db(db.words.count_hard_due, user_id),
        run_db(db.words.get_due_count, user_id),
        run_db(db.learning.get_mistake_word_count, user_id),
        run_db(db.learning.get_daily_goal, user_id),
        run_db(db.learning.get_today_new_words_count, user_id),
        run_db(db.users.get_progress, user_id),
    )

    def _int(value, default=0):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return default

    try:
        streak = _int((progress or {}).get("streak", 0))
    except Exception:
        streak = 0

    return {
        "hard": _int(hard_count),
        "due": _int(due_count),
        "mistakes": _int(mistake_count),
        "goal": _int(daily_goal) or 10,
        "done": _int(today_done),
        "streak": streak,
    }


def _build_stages(state: dict) -> list:
    """مراحل امروز را به ترتیب اولویت یادگیری برمی‌گرداند."""
    stages = []

    if state["hard"] > 0:
        stages.append(
            {
                "plan": f"⚡ مرور {state['hard']} کلمه‌ی سخت معوق",
                "button": "⚡ مرور کلمات سخت",
                "callback": "flashcard_hard",
            }
        )

    if state["due"] > 0:
        stages.append(
            {
                "plan": f"📅 مرور {state['due']} کلمه‌ای که وقتش رسیده",
                "button": "📅 شروع مرور امروز",
                "callback": "flashcard_due",
            }
        )

    if state["mistakes"] > 0:
        stages.append(
            {
                "plan": f"📒 تمرین {state['mistakes']} کلمه‌ی اشتباه باز",
                "button": "🎯 تمرین اشتباهات",
                "callback": f"{CallbackPrefix.QUIZ_SOURCE.value}mistakes",
            }
        )

    remaining_goal = max(0, state["goal"] - state["done"])
    if remaining_goal > 0:
        stages.append(
            {
                "plan": f"🌱 یادگیری {remaining_goal} کلمه‌ی جدید (باقی‌مانده‌ی هدف)",
                "button": "🌱 یادگیری کلمات جدید",
                "callback": "daily_learning",
            }
        )

    return stages


async def show_smart_plan(update, context):
    """نمایش «تمرین هوشمند»: برنامه‌ی تطبیقی امروز + دکمه‌ی اجرای هر مرحله.

    هم از دکمه‌ی reply keyboard («🚀 تمرین هوشمند») و هم به‌صورت inline
    (callback_data=``smart_plan``) قابل فراخوانی است.
    """
    if hasattr(update, "effective_user") and update.effective_user:
        user_id = update.effective_user.id
    elif hasattr(update, "from_user") and update.from_user:
        user_id = update.from_user.id
    else:
        return

    # نکته: احراز هویت در ورودی‌ها انجام شده است
    # (handle_text_input / inline_handler)، بنابراین چک تکراری نداریم.

    state = await _gather_daily_state(user_id)
    stages = _build_stages(state)

    if not stages:
        # ─── همه‌چیز انجام شده → جشن + پیشنهاد تمرین اختیاری ───
        msg = (
            "🎉 <b>فوق‌العاده! برنامه‌ی امروزت کامل شد!</b>\n\n"
            "✅ هیچ کلمه‌ی سخت یا مرور معوقی نداری\n"
            "✅ اشتباه حل‌نشده‌ای باقی نمانده\n"
            "✅ هدف روزانه‌ات هم کامل شده\n\n"
            "برای گرم نگه داشتن ذهن، یک آزمون ترکیبی کوتاه پیشنهاد می‌کنم:"
        )
        keyboard = [
            [
                InlineKeyboardButton(
                    "🤖 آزمون ترکیبی ۱۰ سؤالی", callback_data="mixed_exam:10"
                )
            ],
            [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
        ]
        await render(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # ─── کارت برنامه ───
    goal_bar = progress_bar(state["done"], state["goal"])
    plan_block = "\n".join(
        f"{idx}. {stage['plan']}" for idx, stage in enumerate(stages, start=1)
    )

    streak_line = ""
    if state["streak"] > 0:
        streak_line = f"\n🔥 استریک: <b>{state['streak']}</b> روز"

    msg = (
        "🚀 <b>تمرین هوشمند امروز</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"🎯 هدف امروز: {state['done']}/{state['goal']}  [{goal_bar}]"
        f"{streak_line}\n\n"
        "📋 <b>برنامه‌ی پیشنهادی (به همین ترتیب):</b>\n"
        f"{plan_block}\n\n"
        "💡 <i>اول مرور و اشتباهات، بعد کلمه‌ی جدید؛\n"
        "این‌طوری چیزی که یاد گرفتی فراموش نمی‌شه.</i>\n\n"
        "✅ بعد از تمام‌کردن هر مرحله «🔄 به‌روزرسانی برنامه» را بزن\n"
        "تا مرحله‌ی بعدی مشخص شود."
    )

    # دکمه‌ی اصلی = مرحله‌ی اولویت‌دار فعلی
    primary = stages[0]
    keyboard = [
        [
            InlineKeyboardButton(
                f"▶️ {primary['button']}", callback_data=primary["callback"]
            )
        ]
    ]

    # بقیه‌ی مراحل به‌صورت دکمه‌های دوم (دوتایی در هر ردیف)
    secondary = stages[1:]
    for i in range(0, len(secondary), 2):
        keyboard.append(
            [
                InlineKeyboardButton(s["button"], callback_data=s["callback"])
                for s in secondary[i : i + 2]
            ]
        )

    # به‌روزرسانی برنامه پس از پایان هر مرحله (زنجیره‌سازی سبک)
    keyboard.append(
        [InlineKeyboardButton("🔄 به‌روزرسانی برنامه", callback_data="smart_plan")]
    )
    keyboard.append(
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    )

    await render(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))


__all__ = ["show_smart_plan"]