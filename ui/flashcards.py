"""Flashcard action keyboards."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from models import Word, CallbackPrefix
from core.callbacks import cb_safe


def _flashcard_front_keyboard(
    word: Word, quick_rate: bool = False, token: str = ""
) -> InlineKeyboardMarkup:
    """کیبورد سمت جلوی کارت.
    با quick_rate، ردیف ارزیابی مستقیم هم نمایش داده می‌شود تا کاربرِ
    مطمئن بدون فلیپ، با یک tap ثبت کند."""
    rows = [
        [
            InlineKeyboardButton(
                "👀 نمایش معنی",
                callback_data=cb_safe(
                    CallbackPrefix.FLIP_CARD, f"{token}:{word.id}" if token else word.id
                ),
            )
        ],
    ]
    if quick_rate:
        rows.append(
            [
                InlineKeyboardButton(
                    "😵 Again",
                    callback_data=cb_safe(
                        CallbackPrefix.RATE_CARD,
                        f"{token}:{word.id}:1" if token else f"{word.id}:1",
                    ),
                ),
                InlineKeyboardButton(
                    "😬 Hard",
                    callback_data=cb_safe(
                        CallbackPrefix.RATE_CARD,
                        f"{token}:{word.id}:2" if token else f"{word.id}:2",
                    ),
                ),
                InlineKeyboardButton(
                    "🙂 Good",
                    callback_data=cb_safe(
                        CallbackPrefix.RATE_CARD,
                        f"{token}:{word.id}:3" if token else f"{word.id}:3",
                    ),
                ),
                InlineKeyboardButton(
                    "😎 Easy",
                    callback_data=cb_safe(
                        CallbackPrefix.RATE_CARD,
                        f"{token}:{word.id}:4" if token else f"{word.id}:4",
                    ),
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:front"),
            InlineKeyboardButton(
                "⏭️ رد شدن",
                callback_data=cb_safe(
                    CallbackPrefix.SKIP_FLASHCARD, f"{token}:{word.id}" if token else word.id
                ),
            ),
        ]
    )
    rows.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(rows)


def _flashcard_rate_keyboard(word: Word, token: str = "") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:back")],
            [
                InlineKeyboardButton(
                    "😵 Again",
                    callback_data=cb_safe(
                        CallbackPrefix.RATE_CARD,
                        f"{token}:{word.id}:1" if token else f"{word.id}:1",
                    ),
                ),
                InlineKeyboardButton(
                    "😬 Hard",
                    callback_data=cb_safe(
                        CallbackPrefix.RATE_CARD,
                        f"{token}:{word.id}:2" if token else f"{word.id}:2",
                    ),
                ),
                InlineKeyboardButton(
                    "🙂 Good",
                    callback_data=cb_safe(
                        CallbackPrefix.RATE_CARD,
                        f"{token}:{word.id}:3" if token else f"{word.id}:3",
                    ),
                ),
                InlineKeyboardButton(
                    "😎 Easy",
                    callback_data=cb_safe(
                        CallbackPrefix.RATE_CARD,
                        f"{token}:{word.id}:4" if token else f"{word.id}:4",
                    ),
                ),
            ],
        ]
    )
