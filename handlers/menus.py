from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from models import CallbackPrefix
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
    due = db.words.get_due_count(user_id)
    prog = db.users.get_progress(user_id)
    hard = db.words.count_hard_due(user_id)
    return due, prog["streak"], hard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    if not config.is_authorized_user(user.id):
        await render(update, "⛔️ شما دسترسی ندارید.")
        return

    # ─── ثبت کاربر ───
    db.users.register_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )

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
    is_admin = bool(config.ADMIN_USER_ID and user.id == config.ADMIN_USER_ID)
    await render(
        update,
        welcome,
        reply_markup=get_main_menu_keyboard(due, streak, hard, is_admin=is_admin),
    )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    if not config.is_authorized_user(user.id):
        return

    # ─── ثبت کاربر ───
    db.users.register_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )

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
    is_admin = bool(config.ADMIN_USER_ID and user.id == config.ADMIN_USER_ID)
    await render(
        update,
        msg,
        reply_markup=get_main_menu_keyboard(due, streak, hard, is_admin=is_admin),
    )


async def show_quiz_menu(update, context):
    keyboard = [
        [
            InlineKeyboardButton(
                "🎯 آرتیکل (der/die/das)",
                callback_data=f"{CallbackPrefix.QUIZ_TYPE.value}article",
            )
        ],
        [
            InlineKeyboardButton(
                "🧠 معنی (آلمانی→فارسی)",
                callback_data=f"{CallbackPrefix.QUIZ_TYPE.value}meaning",
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 معکوس (فارسی→آلمانی)",
                callback_data=f"{CallbackPrefix.QUIZ_TYPE.value}reverse",
            )
        ],
        [
            InlineKeyboardButton(
                "📝 جای خالی", callback_data=f"{CallbackPrefix.QUIZ_TYPE.value}cloze"
            )
        ],
        [
            InlineKeyboardButton(
                "✍️ نوشتاری", callback_data=f"{CallbackPrefix.WRITING_START.value}"
            )
        ],
        [
            InlineKeyboardButton(
                "🎧 شنیداری", callback_data=f"{CallbackPrefix.LISTENING_START.value}"
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
                callback_data=f"{CallbackPrefix.QUIZ_SOURCE.value}all",
            )
        ],
        [
            InlineKeyboardButton(
                "📖 از درس خاص",
                callback_data=f"{CallbackPrefix.QUIZ_SOURCE.value}lesson",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ کلمات ضعیف", callback_data=f"{CallbackPrefix.QUIZ_SOURCE.value}weak"
            )
        ],
        [
            InlineKeyboardButton(
                "📅 موعد امروز", callback_data=f"{CallbackPrefix.QUIZ_SOURCE.value}due"
            )
        ],
        [
            InlineKeyboardButton(
                "📒 اشتباهات من",
                callback_data=f"{CallbackPrefix.QUIZ_SOURCE.value}mistakes",
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
    books = db.books.get_all()
    if not books:
        await render(query, "📭 کتابی ندارید.", reply_markup=back_inline_keyboard())
        return
    keyboard = []
    for book_id, name, level in books:
        keyboard.append(
            [
                InlineKeyboardButton(
                    _short_label(f"📖 {name} ({level})"),
                    callback_data=f"{CallbackPrefix.QUIZ_BOOK.value}{book_id}",
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
    lessons = db.lessons.get_by_book(book_id)
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
                    callback_data=f"{CallbackPrefix.QUIZ_LESSON.value}{lesson_id}",
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
        [
            InlineKeyboardButton(
                "⚡ ۵ سوال سریع", callback_data=f"{CallbackPrefix.QUIZ_COUNT.value}5"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 ۱۰ سوال استاندارد",
                callback_data=f"{CallbackPrefix.QUIZ_COUNT.value}10",
            )
        ],
        [
            InlineKeyboardButton(
                "💪 ۲۰ سوال جدی", callback_data=f"{CallbackPrefix.QUIZ_COUNT.value}20"
            )
        ],
        [
            InlineKeyboardButton(
                "🔥 همه کلمات این منبع",
                callback_data=f"{CallbackPrefix.QUIZ_COUNT.value}all",
            )
        ],
        [InlineKeyboardButton("🔙 مرحله قبل", callback_data=back_cb)],
    ]
    await render(
        query,
        "🔢 <b>مرحله ۳/۳: تعداد سوالات</b>\nچند سوال می‌خواهی؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_books(update_or_query, context, is_message: bool = False):
    books = db.books.get_all()
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
    lessons = db.lessons.get_by_book(book_id)
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
    lesson = db.lessons.get_by_id(lesson_id)
    # lesson tuple is (lesson_number, title) from db_legacy.get_lesson
    lesson_name = (
        _format_lesson_name(lesson[1], lesson[2] or "") if lesson else "این درس"
    )
    book_id = db.lessons.get_book_id(lesson_id)
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
    words = db.words.get_by_lesson_full(lesson_id)
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


# ✅ بعد: داشبورد با ساختار بهتر
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

    word_count = db.words.get_count()
    due_today = len(db.words.get_due_today(user_id))
    correct, total = db.users.get_quiz_stats(user_id)
    accuracy = (correct / total * 100) if total > 0 else 0
    prog = db.users.get_progress(user_id)
    level, into, need = db.level_from_xp(prog["xp"])
    hard = db.words.count_hard_due(user_id)
    daily_goal = db.learning.get_daily_goal(user_id)
    today_done = db.learning.get_today_activity_count(user_id)
    goal_bar = progress_bar(today_done, daily_goal)
    bar = progress_bar(into, need)

    # ✅ ساختار بخش‌بندی‌شده
    msg = (
        "📊 <b>داشبورد</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "\n"
        "📈 <b>پیشرفت کلی</b>\n"
        f"   ⭐ سطح {level}  [{bar}]  {into}/{need} XP\n"
        f"   🔥 Streak: <b>{prog['streak']}</b> روز\n"
        f"   🎯 دقت: <b>{accuracy:.1f}%</b>\n"
        "\n"
        "📅 <b>امروز</b>\n"
        f"   🎯 هدف: {today_done}/{daily_goal}  [{goal_bar}]\n"
        f"   📚 مرور: {due_today} کلمه\n"
        f"   📖 کل کتابخانه: {word_count} کلمه\n"
    )

    if today_done >= daily_goal:
        msg += "\n🎉 <b>هدف امروز کامل شد! آفرین!</b>\n"

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
        if hasattr(update, "effective_user") and update.effective_user
        else update.from_user.id
    )
    settings = db.users.get_settings(user_id)
    current_level = settings.get("preferred_level", "A1")
    daily_goal = settings.get("daily_goal", 10)

    keyboard = [
        [InlineKeyboardButton(f"📐 سطح فعلی: {current_level}", callback_data="noop")],
        [InlineKeyboardButton("🔄 تغییر سطح", callback_data="show_level_select")],
        [
            InlineKeyboardButton(
                f"🎯 هدف روزانه: {daily_goal}", callback_data="show_goal_select"
            )
        ],
    ]

    # ─── فقط برای ادمین ───
    if config.ADMIN_USER_ID and user_id == config.ADMIN_USER_ID:
        keyboard.append(
            [InlineKeyboardButton("🛡️ پنل مدیریت", callback_data="admin_panel")]
        )

    # ─── ریست پیشرفت ───
    keyboard.append(
        [InlineKeyboardButton("🗑️ ریست پیشرفت", callback_data="reset_progress")]
    )

    keyboard.append(
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    )

    await render(
        update,
        f"⚙️ <b>تنظیمات</b>\n"
        f"سطح فعلی شما: <b>{current_level}</b>\n"
        f"هدف روزانه: <b>{daily_goal}</b> کلمه",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_level_select(query, context):
    user_id = query.from_user.id
    settings = db.users.get_settings(user_id)
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
    db.users.update_setting(user_id, level)
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


# ─── تنظیم هدف روزانه ───────────────────────────────────────────────

GOALS = [5, 10, 15, 20, 30, 50]


async def show_goal_select(query, context):
    user_id = query.from_user.id
    settings = db.users.get_settings(user_id)
    current_goal = settings.get("daily_goal", 10)

    keyboard = []
    for goal in GOALS:
        marker = "✅ " if goal == current_goal else ""
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{marker}{goal} کلمه", callback_data=f"set_goal:{goal}"
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="show_settings")])
    await render(
        query,
        "🎯 <b>هدف روزانه خود را انتخاب کنید:</b>\n"
        "تعداد کلماتی که هر روز تمرین می‌کنید.",
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
    db.learning.set_daily_goal(user_id, goal)
    await render(
        query,
        f"✅ هدف روزانه شما به <b>{goal}</b> کلمه تغییر کرد!\n"
        "هر روز این تعداد کلمه را تمرین کن تا پیشرفت کنی.",
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
    """نمایش دفترچه اشتباهات حل‌نشده کاربر."""
    user_id = query.from_user.id
    items = db.learning.get_mistake_words(user_id, limit=10)

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
                    callback_data=f"{CallbackPrefix.QUIZ_SOURCE.value}mistakes",
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
