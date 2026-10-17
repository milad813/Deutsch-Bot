"""Quiz Menu handlers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config
import handlers.quiz_handlers as quiz_handlers
from models import CallbackPrefix
from core.callbacks import cb_safe
from services import db, run_db
from ui import _short_label, back_inline_keyboard, render
from ui.text import format_lesson_name as _format_lesson_name


async def show_quiz_menu(update, context):
    keyboard = [
        [
            InlineKeyboardButton(
                "📝 آزمون ترکیبی (پیشنهادی)",
                callback_data=cb_safe(CallbackPrefix.MIXED_EXAM, 20),
            )
        ],
        [
            InlineKeyboardButton(
                "🧠 معنی (آلمانی→فارسی)",
                callback_data=cb_safe(CallbackPrefix.QUIZ_TYPE, "meaning"),
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 معکوس (فارسی→آلمانی)",
                callback_data=cb_safe(CallbackPrefix.QUIZ_TYPE, "reverse"),
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 آرتیکل (der/die/das)",
                callback_data=cb_safe(CallbackPrefix.QUIZ_TYPE, "article"),
            )
        ],
        [
            InlineKeyboardButton(
                "📝 جای خالی",
                callback_data=cb_safe(CallbackPrefix.QUIZ_TYPE, "cloze"),
            )
        ],
        [
            InlineKeyboardButton(
                "🎧 شنیداری",
                callback_data=cb_safe(CallbackPrefix.LISTENING_START),
            )
        ],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
    ]
    await render(
        update,
        "🤖 نوع کوییز را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_quiz_source(query, context):
    keyboard = [
        [
            InlineKeyboardButton(
                "📚 کل کتابخانه من",
                callback_data=cb_safe(CallbackPrefix.QUIZ_SOURCE, "all"),
            )
        ],
        [
            InlineKeyboardButton(
                "📖 از درس خاص",
                callback_data=cb_safe(CallbackPrefix.QUIZ_SOURCE, "lesson"),
            )
        ],
        [
            InlineKeyboardButton(
                "❌ کلمات ضعیف", callback_data=cb_safe(CallbackPrefix.QUIZ_SOURCE, "weak")
            )
        ],
        [
            InlineKeyboardButton(
                "📅 موعد امروز", callback_data=cb_safe(CallbackPrefix.QUIZ_SOURCE, "due")
            )
        ],
        [
            InlineKeyboardButton(
                "📒 اشتباهات من",
                callback_data=cb_safe(CallbackPrefix.QUIZ_SOURCE, "mistakes"),
            )
        ],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="show_quiz_menu")],
    ]
    await render(
        query,
        "📚 <b>مرحله ۲/۳: منبع کلمات</b>\n"
        "از کجا می‌خواهی کوییز بسازم؟\n"
        "📚 کل کتابخانه = همه کلمات\n"
        "📖 از درس خاص = فقط یک درس\n"
        "❌ کلمات ضعیف = بیشتر اشتباه زده‌ای\n"
        "📅 موعد امروز = باید امروز مرور شوند\n"
        "📒 اشتباهات من = کلماتی که قبلاً غلط زدی",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_books_for_quiz(query, context):
    books = await run_db(db.books.get_all)
    if not books:
        await render(query, "📭 کتابی ندارید.", reply_markup=back_inline_keyboard())
        return
    keyboard = []
    for book_id, name, level in books:
        keyboard.append(
            [
                InlineKeyboardButton(
                    _short_label(f"📖 {name} ({level})"),
                    callback_data=cb_safe(CallbackPrefix.QUIZ_BOOK, book_id),
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("🔙 مرحله قبل", callback_data="show_quiz_source")])
    await render(query, "📖 یک کتاب انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_lessons_for_quiz(query, context, book_id: int):
    """List a book's lessons as quiz sources (CallbackPrefix.QUIZ_LESSON).

    The callback router's ``_handle_quiz_book`` calls this after the user
    picks a book in the quiz-by-lesson flow; the picked lesson id is stored
    as ``quiz_lesson_id`` by ``_handle_quiz_lesson``.
    """
    lessons = await run_db(db.lessons.get_by_book, book_id)
    if not lessons:
        await render(
            query,
            "📭 این کتاب درسی ندارد.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 مرحله قبل",
                            callback_data=cb_safe(CallbackPrefix.QUIZ_SOURCE, "lesson"),
                        )
                    ]
                ]
            ),
        )
        return

    kb = []
    for lesson_id, num, title in lessons:
        kb.append(
            [
                InlineKeyboardButton(
                    _short_label(f"📝 {_format_lesson_name(num, title or '')}"),
                    callback_data=cb_safe(CallbackPrefix.QUIZ_LESSON, lesson_id),
                )
            ]
        )

    kb.append(
        [
            InlineKeyboardButton(
                "🔙 مرحله قبل",
                callback_data=cb_safe(CallbackPrefix.QUIZ_SOURCE, "lesson"),
            )
        ]
    )
    await render(query, "📖 یک درس انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))


async def start_mixed_exam(query, context, count: int = 20):
    """شروع سریع آزمون ترکیبی - فقط از کلمات دیده‌شده."""
    user_id = query.from_user.id

    # ✅ فقط کلماتی که کاربر حداقل یک‌بار تعامل داشته
    available = await run_db(db.words.get_seen_count, user_id)
    if available == 0:
        await render(
            query,
            "📭 هنوز کلمه‌ای نخونده‌ای!\n"
            "اول با فلش‌کارت یا LTR چند کلمه یاد بگیر، بعد بیا آزمون بده. 📚",
            reply_markup=back_inline_keyboard(),
        )
        return

    count = min(count, available, config.MAX_QUIZ_ALL_COUNT)

    # ریست state قبلی
    context.user_data.pop("quiz_lesson_id", None)
    context.user_data.pop("quiz_lesson_preset", None)
    context.user_data.pop("quiz_fixed_word_ids", None)

    # ✅ source_filter="seen" → فقط کلمات دیده‌شده
    await quiz_handlers.start_quiz_session(query, context, "mixed", count, "seen")


async def show_quiz_count(query, context):
    back_cb = "show_quiz_source"
    if context.user_data.get("quiz_lesson_preset"):
        lesson_id = context.user_data.get("quiz_lesson_id")
        back_cb = f"lesson_{lesson_id}" if lesson_id else "back_to_main_menu"
    keyboard = [
        [
            InlineKeyboardButton(
                "⚡ ۵ سوال سریع", callback_data=cb_safe(CallbackPrefix.QUIZ_COUNT, 5)
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 ۱۰ سوال استاندارد",
                callback_data=cb_safe(CallbackPrefix.QUIZ_COUNT, 10),
            )
        ],
        [
            InlineKeyboardButton(
                "💪 ۲۰ سوال جدی", callback_data=cb_safe(CallbackPrefix.QUIZ_COUNT, 20)
            )
        ],
        [
            InlineKeyboardButton(
                "🔥 همه کلمات این منبع",
                callback_data=cb_safe(CallbackPrefix.QUIZ_COUNT, "all"),
            )
        ],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data=back_cb)],
    ]
    await render(
        query,
        "🔢 <b>مرحله ۳/۳: تعداد سوالات</b>\nچند سوال می‌خواهی؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
