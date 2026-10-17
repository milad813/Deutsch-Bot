"""Keyboard builders (inline + reply).

Extracted from the former root ``ui.py`` in Phase R3. Every dynamic
button's callback_data goes through :func:`core.callbacks.cb_safe` so an
over-long payload degrades to ``"noop"`` instead of crashing the
keyboard at send time.
"""

from typing import Any, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from core.callbacks import CallbackPrefix, cb_safe
from ui.text import _short_label


def callback_button(
    text: str,
    prefix: CallbackPrefix,
    suffix: Any = "",
) -> InlineKeyboardButton:
    """Build an ``InlineKeyboardButton`` with a length-safe callback_data.

    The label is truncated to 64 characters (Telegram's display limit for
    button text), and the callback data is routed through :func:`cb_safe`
    so that an over-long payload — for example a pathological ``lesson_id``
    or an unbounded suffix — degrades to ``"noop"`` instead of crashing
    the keyboard at send-time with ``BadRequest: Button_data_invalid``.

    Use this helper for every dynamic inline button whose
    ``callback_data`` is composed from a :class:`CallbackPrefix` plus a
    variable suffix. Static-literal buttons may keep
    ``InlineKeyboardButton(text, callback_data="foo")``.
    """
    return InlineKeyboardButton(
        text=_short_label(text, 64),
        callback_data=cb_safe(prefix, suffix),
    )


def main_menu_keyboard(
    due_count: int = 0, streak: int = 0, hard_count: int = 0, is_admin: bool = False
) -> ReplyKeyboardMarkup:
    keyboard = []

    # ─── ردیف اول: برنامه‌ی تطبیقی روز (اقدام پیشنهادی) ───
    keyboard.append(["🚀 تمرین هوشمند"])

    # ─── ردیف اقدام فوری (میان‌بر مستقیم) ───
    if hard_count > 0:
        keyboard.append([f"🔥 مرور کلمات سخت ({hard_count})"])
    elif due_count > 0:
        keyboard.append([f"📅 مرور امروز ({due_count} کلمه)"])

    # ─── ردیف یادگیری ───
    keyboard.append(["📚 کتاب و درس‌ها", "🎴 فلش‌کارت"])

    # ─── ردیف تمرین و آمار ───
    keyboard.append(["🤖 کوییز", "📊 داشبورد"])

    # ─── ردیف تنظیمات و مدیریت ───
    if is_admin:
        keyboard.append(["⚙️ تنظیمات", "🛡️ پنل مدیریت"])
    else:
        keyboard.append(["⚙️ تنظیمات"])

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def back_inline_keyboard(
    text: str = "🏠 منوی اصلی",
    callback_data: str = "back_to_main_menu",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=callback_data)]])


def quiz_answer_keyboard(options: List[str], token: str = "") -> InlineKeyboardMarkup:
    keyboard = []
    for i, opt in enumerate(options or []):
        keyboard.append(
            [
                callback_button(
                    _short_label(opt, 64),
                    CallbackPrefix.QUIZ_ANS,
                    f"{token}:{i}" if token else i,
                )
            ]
        )
    return InlineKeyboardMarkup(keyboard)
