from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from services import db, get_main_menu_keyboard, reset_session
from ui import _short_label, back_inline_keyboard, esc, render

ITEMS_PER_PAGE = 5


def _format_lesson_name(num: int, title: str) -> str:
    if not title:
        return f"درس {num}"
    clean_title = title.strip()
    if clean_title.startswith(f"درس {num}") or clean_title.startswith(f"درس{num}"):
        return clean_title
    return f"درس {num}: {clean_title}"


def _menu_stats(user_id: int):
    due = db.get_due_word_count(user_id)
    prog = db.get_user_progress(user_id)
    hard = db.count_hard_due_words(user_id)
    return due, prog["streak"], hard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not config.is_authorized_user(user.id):
        await render(update, "⛔️ شما دسترسی ندارید.")
        return
    reset_session(context)
    due, streak, hard = _menu_stats(user.id)
    welcome = (
        f"سلام {esc(user.first_name)} عزیز! 👋\n"
        "به ربات یادگیری زبان آلمانی خوش آمدی! 🇩🇪\n"
    )
    if streak > 0:
        welcome += f"🔥 streak فعلی: {streak} روز\n"
    if hard > 0:
        welcome += f"⚡ {hard} کلمه‌ی سخت معوق داری.\n"
    elif due > 0:
        welcome += f"📅 {due} کلمه برای مرور داری!\n"
    welcome += "از منوی زیر شروع کن! 🚀"
    await render(
        update, welcome, reply_markup=get_main_menu_keyboard(due, streak, hard)
    )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not config.is_authorized_user(user.id):
        return
    reset_session(context)
    due, streak, hard = _menu_stats(user.id)
    msg = "🏠 <b>منوی اصلی</b>\n"
    if streak > 0:
        msg += f"🔥 streak: {streak} روز\n"
    if hard > 0:
        msg += f"⚡ {hard} کلمه‌ی سخت معوق\n"
    elif due > 0:
        msg += f"📅 {due} کلمه برای مرور داری!\n"
    else:
        msg += "🎉 همه مرورها انجام شده!\n"
    await render(update, msg, reply_markup=get_main_menu_keyboard(due, streak, hard))


async def show_quiz_menu(update, context):
    keyboard = [
        [
            InlineKeyboardButton(
                "🎯 آرتیکل (der/die/das)", callback_data="quiz_type:article"
            )
        ],
        [
            InlineKeyboardButton(
                "🧠 معنی (آلمانی→فارسی)", callback_data="quiz_type:meaning"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 معکوس (فارسی→آلمانی)", callback_data="quiz_type:reverse"
            )
        ],
        [InlineKeyboardButton("📝 جای خالی", callback_data="quiz_type:cloze")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
    ]
    await render(
        update,
        "🤖 نوع کوییز را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_quiz_source(query, context):
    keyboard = [
        [InlineKeyboardButton("📚 کل کتابخانه من", callback_data="quiz_source:all")],
        [InlineKeyboardButton("📖 از درس خاص", callback_data="quiz_source:lesson")],
        [InlineKeyboardButton("❌ کلمات ضعیف", callback_data="quiz_source:weak")],
        [InlineKeyboardButton("📅 موعد امروز", callback_data="quiz_source:due")],
        [InlineKeyboardButton("📒 اشتباهات من", callback_data="quiz_source:mistakes")],
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
    books = db.get_all_books()
    if not books:
        await render(query, "📭 کتابی ندارید.", reply_markup=back_inline_keyboard())
        return
    keyboard = []
    for book_id, name, level in books:
        keyboard.append(
            [
                InlineKeyboardButton(
                    _short_label(f"📖 {name} ({level})"),
                    callback_data=f"quiz_book:{book_id}",
                )
            ]
        )
    keyboard.append(
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data="show_quiz_source")]
    )
    await render(
        query, "📖 یک کتاب انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_lessons_for_quiz(query, context, book_id):
    lessons = db.get_lessons_by_book(book_id)
    if not lessons:
        await render(
            query,
            "📭 درسی ندارد.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 بازگشت", callback_data="show_quiz_source")]]
            ),
        )
        return
    keyboard = []
    for lesson_id, num, title in lessons:
        keyboard.append(
            [
                InlineKeyboardButton(
                    _short_label(f"📝 {_format_lesson_name(num, title or '')}"),
                    callback_data=f"quiz_lesson:{lesson_id}",
                )
            ]
        )
    keyboard.append(
        [InlineKeyboardButton("🔙 بازگشت", callback_data="show_quiz_source")]
    )
    await render(
        query, "📖 یک درس انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_quiz_count(query, context):
    back_cb = "show_quiz_source"
    if context.user_data.get("quiz_lesson_preset"):
        lesson_id = context.user_data.get("quiz_lesson_id")
        back_cb = f"lesson_{lesson_id}" if lesson_id else "back_to_main_menu"
    keyboard = [
        [InlineKeyboardButton("⚡ ۵ سوال سریع", callback_data="quiz_count:5")],
        [InlineKeyboardButton("🎯 ۱۰ سوال استاندارد", callback_data="quiz_count:10")],
        [InlineKeyboardButton("💪 ۲۰ سوال جدی", callback_data="quiz_count:20")],
        [InlineKeyboardButton("🔥 همه کلمات این منبع", callback_data="quiz_count:all")],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data=back_cb)],
    ]
    await render(
        query,
        "🔢 <b>مرحله ۳/۳: تعداد سوالات</b>\nچند سوال می‌خواهی؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_books(update_or_query, context, is_message: bool = False):
    books = db.get_all_books()
    if not books:
        text = "📭 کتابی ندارید."
        kb = [[InlineKeyboardButton("🔙", callback_data="back_to_main_menu")]]
    else:
        text = "📚 یک کتاب انتخاب کنید:"
        kb = [
            [
                InlineKeyboardButton(
                    _short_label(f"📖 {name} ({level})"),
                    callback_data=f"book_{book_id}",
                )
            ]
            for book_id, name, level in books
        ]
        kb.append([InlineKeyboardButton("🔙", callback_data="back_to_main_menu")])
    await render(update_or_query, text, reply_markup=InlineKeyboardMarkup(kb))


async def show_lessons(query, context, book_id: int):
    lessons = db.get_lessons_by_book(book_id)
    if not lessons:
        await render(
            query,
            "📭 درسی ندارد.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙", callback_data="show_books_inline")]]
            ),
        )
        return
    kb = [
        [
            InlineKeyboardButton(
                _short_label(f"📝 {_format_lesson_name(num, title or '')}"),
                callback_data=f"lesson_{lesson_id}",
            )
        ]
        for lesson_id, num, title in lessons
    ]
    kb.append([InlineKeyboardButton("🔙", callback_data="show_books_inline")])
    await render(query, "📖 یک درس انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))


async def show_lesson_options(query, context, lesson_id: int):
    lesson = db.get_lesson(lesson_id)
    # lesson tuple is (lesson_number, title) from db_legacy.get_lesson
    lesson_name = (
        _format_lesson_name(lesson[0], lesson[1] or "") if lesson else "این درس"
    )
    book_id = db.get_book_id_by_lesson(lesson_id)
    back_cb = f"book_{book_id}" if book_id else "show_books_inline"
    keyboard = [
        [
            InlineKeyboardButton(
                "📋 مشاهده لیست کلمات", callback_data=f"lesson_words_{lesson_id}_0"
            )
        ],
        [
            InlineKeyboardButton(
                "🧠 تمرین عمیق (LTR)", callback_data=f"study_lesson:{lesson_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "📖 داستان این درس", callback_data=f"story_lesson:{lesson_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🎴 فلش‌کارت", callback_data=f"flashcard_lesson:{lesson_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🤖 کوییز", callback_data=f"quiz_from_lesson:{lesson_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "📐 گرامر این درس", callback_data=f"grammar_lesson:{lesson_id}"
            )
        ],
        [InlineKeyboardButton("🔙 بازگشت به لیست درس‌ها", callback_data=back_cb)],
    ]
    await render(
        query,
        f"📚 <b>{esc(lesson_name)}</b>\nچه کاری می‌خواهی انجام بدی؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_lesson_words(query, context, lesson_id: int, page: int = 0):
    words = db.get_words_by_lesson_full(lesson_id)
    if not words:
        await render(
            query,
            "📭 کلمه‌ای ندارد.",
            reply_markup=back_inline_keyboard("🔙 بازگشت", f"lesson_{lesson_id}"),
        )
        return
    total = len(words)
    max_page = max(0, (total - 1) // ITEMS_PER_PAGE)
    if page < 0:
        page = 0
    if page > max_page:
        page = max_page
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_words = words[start:end]

    type_emoji = {
        "Noun": "🏷️",
        "Verb": "🏃",
        "Adjective": "🎨",
        "Adverb": "➡️",
        "Preposition": "📍",
        "Pronoun": "👤",
        "Conjunction": "🔗",
        "Phrase": "💬",
        "سایر": "📌",
    }

    msg = f"📝 کلمات درس ({total} کلمه) - صفحه {page + 1}\n"
    for w in page_words:
        wtype = w.get("word_type") or "سایر"
        emoji = type_emoji.get(wtype, "📌")
        line = f"{emoji} "
        if w.get("article"):
            line += f"{esc(w['article'])} "
        line += f"<b>{esc(w['german'])}</b> — {esc(w['persian'])}"
        if w.get("english_meaning"):
            line += f"\n🇬🇧 {esc(w['english_meaning'])}"
        if w.get("plural"):
            line += f" ({esc(w['plural'])})"
        if w.get("verb_forms"):
            line += f"\n→ {esc(w['verb_forms'])}"
        if w.get("comparative"):
            line += f"\n→ {esc(w['comparative'])}"
        if w.get("collocation_de"):
            coll_de = esc(w["collocation_de"])
            coll_fa = esc(w["collocation_fa"]) if w.get("collocation_fa") else ""
            line += f"\n🔗 {coll_de}" + (f" — {coll_fa}" if coll_fa else "")
        if w.get("example_de"):
            line += f"\n📝 {esc(w['example_de'])}"
        if w.get("example_fa"):
            line += f"\n🇮🇷 <i>{esc(w['example_fa'])}</i>"
        msg += line + "\n"

    keyboard = []
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️ قبلی", callback_data=f"lesson_words_{lesson_id}_{page - 1}"
            )
        )
    if end < total:
        nav.append(
            InlineKeyboardButton(
                "➡️ بعدی", callback_data=f"lesson_words_{lesson_id}_{page + 1}"
            )
        )
    if nav:
        keyboard.append(nav)
    keyboard.append(
        [InlineKeyboardButton("🔙 بازگشت به درس", callback_data=f"lesson_{lesson_id}")]
    )
    await render(query, msg, reply_markup=InlineKeyboardMarkup(keyboard))


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

    word_count = db.get_word_count()
    due_today = len(db.get_words_due_today(user_id))
    correct, total = db.get_quiz_stats(user_id)
    accuracy = (correct / total * 100) if total > 0 else 0
    prog = db.get_user_progress(user_id)
    level, into, need = db.level_from_xp(prog["xp"])
    hard = db.count_hard_due_words(user_id)

    bar = progress_bar(into, need)
    msg = (
        f"📊 <b>داشبورد</b>\n"
        f"📚 کل کلمات: {word_count}\n"
        f"📅 مرور امروز: {due_today} کلمه\n"
        f"🎯 دقت کلی: {accuracy:.1f}%\n"
        f"🔥 streak: {prog['streak']} روز\n"
        f"⭐ سطح {level}  [{bar}]  {into}/{need} XP\n"
    )

    keyboard = []
    if hard > 0:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔥 مرور کلمات سخت ({hard})", callback_data="flashcard_hard"
                )
            ]
        )
    if due_today > 0:
        keyboard.append(
            [InlineKeyboardButton("🚀 شروع مرور", callback_data="flashcard_due")]
        )
    keyboard.append(
        [InlineKeyboardButton("📒 اشتباهات من", callback_data="show_error_notebook")]
    )
    keyboard.append(
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    )
    await render(update, msg, reply_markup=InlineKeyboardMarkup(keyboard))


# ─── تنظیمات سطح ───────────────────────────────────────────────

LEVELS = ["A1", "A2", "B1", "B2"]


async def show_settings_menu(update, context):
    user_id = (
        update.effective_user.id
        if hasattr(update, "effective_user")
        else update.from_user.id
    )
    settings = db.get_user_settings(user_id)
    current_level = settings.get("preferred_level", "A1")

    keyboard = [
        [InlineKeyboardButton(f"📐 سطح فعلی: {current_level}", callback_data="noop")],
        [InlineKeyboardButton("🔄 تغییر سطح", callback_data="show_level_select")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
    ]
    await render(
        update,
        f"⚙️ <b>تنظیمات</b>\nسطح فعلی شما: <b>{current_level}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_level_select(query, context):
    user_id = query.from_user.id
    settings = db.get_user_settings(user_id)
    current_level = settings.get("preferred_level", "A1")

    keyboard = []
    for lvl in LEVELS:
        marker = "✅ " if lvl == current_level else ""
        keyboard.append(
            [InlineKeyboardButton(f"{marker}{lvl}", callback_data=f"set_level:{lvl}")]
        )
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="show_settings")])
    await render(
        query,
        "📐 <b>سطح زبان خود را انتخاب کنید:</b>\n"
        "این سطح در مثال‌ها، داستان‌ها و کوییزهای LLM استفاده می‌شود.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_set_level(query, context, suffix: str):
    level = suffix.strip().upper()
    if level not in LEVELS:
        await render(query, "⚠️ سطح نامعتبر.", reply_markup=back_inline_keyboard())
        return
    user_id = query.from_user.id
    db.update_user_setting(user_id, level)
    await render(
        query,
        f"✅ سطح شما به <b>{level}</b> تغییر کرد!\n"
        "از الان مثال‌ها و داستان‌ها با این سطح ساخته می‌شوند.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⚙️ تنظیمات", callback_data="show_settings")],
                [
                    InlineKeyboardButton(
                        "🔙 منوی اصلی", callback_data="back_to_main_menu"
                    )
                ],
            ]
        ),
    )


# ─────────────────────────────
# Error Notebook (مرحله ۳)
# ─────────────────────────────
async def show_error_notebook(query, context):
    """نمایش دفترچه اشتباهات کاربر."""
    user_id = query.from_user.id
    items = db.get_weakest_words_by_skills(user_id, limit=10)

    if not items:
        await render(
            query,
            "📒 <b>دفترچه اشتباهات</b>\n\nهنوز اشتباهی ثبت نشده! 🎉\n"
            "با انجام کوییز و فلش‌کارت، اشتباهاتت ذخیره می‌شوند.",
            reply_markup=back_inline_keyboard(),
        )
        return

    msg = "📒 <b>دفترچه اشتباهات</b>\n\n"

    for item in items[:10]:
        word = item["word"]
        msg += (
            f"🔸 <b>{esc(word.display_german)}</b> — {esc(word.persian)}\n"
            f"❌ {item['wrong']} اشتباه | ✅ {item['correct']} درست | "
            f"🎯 تسلط: {item['mastery']}%\n\n"
        )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎯 تمرین اشتباهات",
                    callback_data="quiz_source:mistakes",
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
