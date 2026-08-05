import logging
from typing import Optional
from collections import deque

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import random
import config

from services import db, fsrs, llm
from models import Word
from ui import esc, back_inline_keyboard, _bold_word_in_sentence, render, _short_label, progress_bar
logger = logging.getLogger(__name__)


def _flashcard_front_keyboard(word: Word) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:front")],
        [InlineKeyboardButton("👀 نشان بده معنی", callback_data=f"flip_card:{word.id}")],
        [InlineKeyboardButton("⏭️ رد شدن", callback_data=f"skip_flashcard:{word.id}")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
    ])


def _flashcard_rate_keyboard(word: Word) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:back")],
        [InlineKeyboardButton("😵 Again", callback_data=f"rate_card:{word.id}:1")],
        [InlineKeyboardButton("😬 Hard", callback_data=f"rate_card:{word.id}:2")],
        [InlineKeyboardButton("🙂 Good", callback_data=f"rate_card:{word.id}:3")],
        [InlineKeyboardButton("😎 Easy", callback_data=f"rate_card:{word.id}:4")],
    ])


async def _send_or_edit(query, update, text: str, reply_markup):
    await render(query or update, text, reply_markup=reply_markup)


def _get_level_for_context(context, user_id: int) -> str:
    lesson_id = (
        context.user_data.get("active_lesson_id")
        or context.user_data.get("ltr_lesson_id")
        or context.user_data.get("study_lesson_id")
    )

    if lesson_id:
        level = db.get_book_level_by_lesson(lesson_id)
        if level:
            return level

    settings = db.get_user_settings(user_id)
    return settings.get("preferred_level", "A1")


# ============================================================
# Flashcard
# ============================================================

async def start_flashcard_session(update, context, lesson_id: Optional[int] = None, only_new: bool = False, only_due: bool = False, pending_only: bool = False):    
    query = getattr(update, "callback_query", None)
    if query is None and hasattr(update, "data"):
        query = update
    user_id = query.from_user.id if query else update.effective_user.id
    context.user_data["active_lesson_id"] = lesson_id
    context.user_data["flashcard_only_new"] = only_new
    context.user_data["flashcard_only_due"] = only_due
    context.user_data["flashcard_pending_only"] = pending_only
    context.user_data["flashcard_skipped_ids"] = set()
    if pending_only:
        ids = db.get_pending_review_word_ids(user_id)
        words = db.get_word_objects_by_ids(ids) if ids else []
    elif only_due:
        words = db.get_due_word_objects(
            user_id, limit=config.FLASHCARD_QUEUE_LIMIT, lesson_id=lesson_id,
        )
    else:
        words = fsrs.get_review_cards(
            user_id,
            limit=config.FLASHCARD_QUEUE_LIMIT,
            lesson_id=lesson_id,
            include_new=True,
            new_limit=config.FLASHCARD_NEW_LIMIT,
            only_new=only_new,
        )
    if not words:
        if pending_only:
            msg = "🎉 هیچ کلمه‌ی سختِ معوقی نداری!"
        elif only_due:
            msg = "🎉 آفرین! هیچ کلمه‌ای برای مرور نداری!"
        elif only_new:
            msg = "🎉 همه کلمات جدید این درس را قبلاً دیده‌ای!"
        else:
            msg = "🎉 آفرین! هیچ کلمه‌ای برای مرور نداری!"
        await _send_or_edit(query, update, msg, back_inline_keyboard())
        return
    context.user_data["flashcard_queue"] = deque([w.id for w in words[1:]])
    await _render_flashcard_front(query, update, context, words[0])

async def _render_flashcard_front(query, update, context, word: Word, notice: Optional[str] = None):
    if query:
        user_id = query.from_user.id
    elif hasattr(update, "effective_user") and update.effective_user:
        user_id = update.effective_user.id
    else:
        user_id = None
    context.user_data['current_flashcard'] = {'word_id': word.id}
    context.user_data.pop('flashcard_rate_lock', None)

    example = None
    if user_id and llm.is_available():
        try:
            level = _get_level_for_context(context, user_id)
            example = await llm.generate_contextual_example(
                word.german, article=word.article, meaning=word.persian, level=level,
            )
        except Exception as e:
            logger.warning("خطا در تولید مثال: %s", e)
    context.user_data["current_flashcard"]["example"] = example
    queue = context.user_data.get("flashcard_queue")
    remaining = (len(queue) + 1) if isinstance(queue, deque) else 1
    parts = []
    if notice:
        parts.append(notice)
    parts.append(f"🎴 <b>فلش‌کارت</b> | 📊 {remaining} کارت باقی‌مانده")
    speak_text = word.display_german
    if example and example.get("de"):
        sentence_with_bold = _bold_word_in_sentence(example["de"], word.german)
        if "<b>" in sentence_with_bold:
            parts.append(f"🇩🇪 {sentence_with_bold}")
            parts.append("💡 معنی کلمه‌ی <b>بولدشده</b> چیست؟")
            speak_text = example["de"]
        else:
            parts.append(f"🇩🇪 <b>{esc(word.display_german)}</b>")
            parts.append("💡 فکر کن... معنی چیست؟")
    else:
        parts.append(f"🇩🇪 <b>{esc(word.display_german)}</b>")
        parts.append("💡 فکر کن... معنی چیست؟")
    context.user_data["current_tts_text"] = speak_text
    await _send_or_edit(query, update, "\n".join(parts), _flashcard_front_keyboard(word))


async def handle_flip_card(query, context, suffix: str = None):
    try:
        word_id = int(suffix) if suffix else int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await render(query, "❌ کارت نامعتبر.", reply_markup=back_inline_keyboard())
        return
    word = db.get_word_by_id(word_id)
    if not word:
        await render(query, "❌ کلمه پیدا نشد.", reply_markup=back_inline_keyboard())
        return
    fc_data = context.user_data.get("current_flashcard", {}) or {}
    example = fc_data.get("example")
    example_de = None
    example_fa = None
    if example and example.get("de"):
        example_de = example["de"]
        example_fa = example.get("fa")
    elif word.example_de:
        example_de = word.example_de
        example_fa = word.example_fa
    msg = "🎴 <b>فلش‌کارت</b>\n"
    speak_text = word.display_german
    show_example = False
    if example_de:
        sentence_with_bold = _bold_word_in_sentence(example_de, word.german)
        if "<b>" in sentence_with_bold:
            msg += f"🇩🇪 {sentence_with_bold}\n"
        if example_fa:
            msg += f"🇮🇷 <i>{esc(example_fa)}</i>\n"
        msg += f"\n📌 <b>{esc(word.display_german)}</b> = {esc(word.persian)}\n"
        speak_text = example_de
        show_example = True
    if not show_example:
        msg += f"🇩🇪 {esc(word.display_german)}\n"
        msg += f"🇮🇷 <b>{esc(word.persian)}</b>\n"
    if word.english_meaning:
        msg += f"🇬🇧 {esc(word.english_meaning)}\n"
    if word.extra_forms_line:
        msg += f"📖 {esc(word.extra_forms_line)}\n"
    if word.collocation_line:
        msg += f"🔗 {esc(word.collocation_line)}\n"
    if not context.user_data.get("fsrs_guide_shown"):
        msg += (
            "\n<b>راهنمای ارزیابی:</b>\n"
            "😵 Again = اصلاً یادم نبود\n"
            "😬 Hard = به‌سختی یادم آمد\n"
            "🙂 Good = یادم آمد\n"
            "😎 Easy = خیلی راحت بود\n"
        )
        context.user_data["fsrs_guide_shown"] = True
    msg += "\nحالا صادقانه: چقدر بلد بودی؟"
    context.user_data["current_tts_text"] = speak_text
    await render(query, msg, reply_markup=_flashcard_rate_keyboard(word))

async def handle_rate_card(query, context, suffix: str = None):
    try:
        if suffix and ":" in suffix:
            word_id_s, grade_s = suffix.split(":", 1)
        else:
            _, word_id_s, grade_s = query.data.split(":", 2)

        word_id = int(word_id_s)
        grade = int(grade_s)
    except Exception:
        await render(query, "❌ کارت نامعتبر.", reply_markup=back_inline_keyboard())
        return

    user_id = query.from_user.id

    lock_value = str(word_id)
    if context.user_data.get('flashcard_rate_lock') == lock_value:
        try:
            await query.answer()
        except Exception:
            pass
        return

    current = context.user_data.get('current_flashcard') or {}
    if current.get('word_id') != word_id:
        try:
            await query.answer('⚠️ این کارت منقضی شده.', show_alert=True)
        except Exception:
            pass
        return

    context.user_data['flashcard_rate_lock'] = lock_value

    _, interval_days = fsrs.review_flashcard(user_id, word_id, grade)
    db.record_activity(user_id, 5)
    if not context.user_data.get("flashcard_pending_only"):
        if grade == 1:
            db.add_pending_review(user_id, word_id)
    else:
        db.clear_pending_reviews(user_id, [word_id])
    grade_names = {1: "😵 Again", 2: "😬 Hard", 3: "🙂 Good", 4: "😎 Easy"}
    notice = f"✅ {grade_names.get(grade, grade)} ثبت شد (مرور بعدی: {interval_days} روز)"

    await _go_next_flashcard(query, context, notice=notice)


async def handle_next_flashcard(query, context, suffix: str = None):
    await _go_next_flashcard(query, context, notice=None)


async def handle_skip_flashcard(query, context, suffix: str = None):
    fc = context.user_data.get("current_flashcard") or {}
    word_id = fc.get("word_id")

    if word_id:
        skipped = context.user_data.setdefault("flashcard_skipped_ids", set())
        skipped.add(word_id)

    await _go_next_flashcard(query, context, notice="⏭️ رد شد")

async def _go_next_flashcard(query, context, notice: Optional[str] = None):
    user_id = query.from_user.id
    lesson_id = context.user_data.get("active_lesson_id")
    only_new = context.user_data.get("flashcard_only_new", False)
    only_due = context.user_data.get("flashcard_only_due", False)

    queue = context.user_data.get("flashcard_queue")
    if not isinstance(queue, deque):
        queue = deque(queue or [])
    context.user_data["flashcard_queue"] = queue

    while queue:
        word_id = queue.popleft()
        word = db.get_word_by_id(word_id)
        if word:
            await _render_flashcard_front(query, None, context, word, notice=notice)
            return
    if context.user_data.get("flashcard_pending_only", False):
        context.user_data.pop("current_flashcard", None)
        context.user_data.pop("flashcard_queue", None)
        context.user_data.pop("current_tts_text", None)
        context.user_data.pop("flashcard_skipped_ids", None)
        context.user_data.pop("flashcard_pending_only", None)
        await render(
            query,
            "🎉 مرور کلمات سخت امروز تمام شد! آفرین! 🔥",
            reply_markup=back_inline_keyboard(),
        )
        return
    last_word_id = context.user_data.get("current_flashcard", {}).get("word_id")
    skipped = context.user_data.get("flashcard_skipped_ids", set())
    exclude_ids = {last_word_id} if last_word_id else set()
    exclude_ids.update(skipped)

    if only_due:
        # حالت «مرور امروز»: refill هم فقط due، بدون جدید
        words = db.get_due_word_objects(
            user_id, limit=config.FLASHCARD_QUEUE_LIMIT, lesson_id=lesson_id,
            exclude_ids=exclude_ids,
        )
    else:
        words = fsrs.get_review_cards(
            user_id, limit=config.FLASHCARD_QUEUE_LIMIT, lesson_id=lesson_id,
            include_new=True, new_limit=config.FLASHCARD_NEW_LIMIT,
            exclude_ids=exclude_ids, only_new=only_new,
        )

    if words:
        context.user_data["flashcard_queue"] = deque([w.id for w in words[1:]])
        await _render_flashcard_front(query, None, context, words[0], notice=notice)
    else:
        context.user_data.pop("current_flashcard", None)
        context.user_data.pop("flashcard_queue", None)
        context.user_data.pop("current_tts_text", None)
        context.user_data.pop("flashcard_skipped_ids", None)
        if only_new:
            msg = "🎉 کلمات جدید این درس تمام شد!"
        elif only_due:
            msg = "🎉 مرور امروز تمام شد! آفرین!"
        else:
            msg = "🎉 آفرین! همه کلمات مرور شدند!"
        await render(query, msg, reply_markup=back_inline_keyboard())

# ============================================================
# LTR Session (Learn-Test-Repeat)
# ============================================================
def _sample_unique_ltr(primary: list, secondary: list, count: int) -> list:
    random.shuffle(primary)
    random.shuffle(secondary)

    result = []
    for item in primary + secondary:
        item = str(item or "").strip()
        if item and item not in result:
            result.append(item)
        if len(result) == count:
            break

    return result


def _make_ltr_options(correct: str, wrongs: list, total: int = 4, min_options: int = 1) -> Optional[list]:
    correct = str(correct or "").strip()
    if not correct:
        return None

    options = [correct]
    for wrong in wrongs or []:
        wrong = str(wrong or "").strip()
        if not wrong or wrong in options:
            continue
        options.append(wrong)
        if len(options) == total:
            break

    if len(options) < min_options:
        return None

    random.shuffle(options)
    return options


def _ltr_wrong_display_german_options(word: Word, count: int = 3) -> list:
    same_type_words = db.get_words_by_type(word.word_type, exclude_id=word.id, limit=50) if word.word_type else []
    other_words = db.get_words_by_type(None, exclude_id=word.id, limit=50)

    same_type = [
        w.display_german for w in same_type_words
        if w.display_german and w.display_german != word.display_german
    ]
    other = [
        w.display_german for w in other_words
        if w.display_german
        and w.display_german != word.display_german
        and (not word.word_type or w.word_type != word.word_type)
    ]

    return _sample_unique_ltr(same_type, other, count)


def _ltr_answer_keyboard(options: list, with_tts: bool = False) -> InlineKeyboardMarkup:
    rows = []

    for i, opt in enumerate(options):
        label = f"{chr(65 + i)}) {opt}"
        rows.append([InlineKeyboardButton(_short_label(label, 64), callback_data=f"ltr_ans:{i}")])

    if with_tts:
        rows.append([InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:study")])

    rows.append([InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")])

    return InlineKeyboardMarkup(rows)


def _ltr_intro_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:study")],
        [InlineKeyboardButton("✅ فهمیدم، بریم!", callback_data="ltr_ready")],
        [InlineKeyboardButton("🏁 پایان جلسه", callback_data="ltr_exit")],
    ])


def _schedule_delayed_task(context, word_id: int, stage: str, delay_main: int):
    tasks = context.user_data.setdefault("ltr_delayed_tasks", [])
    if not isinstance(tasks, list):
        tasks = []
        context.user_data["ltr_delayed_tasks"] = tasks

    tasks[:] = [
        t for t in tasks
        if not (isinstance(t, dict) and t.get("word_id") == word_id and t.get("stage") == stage)
    ]

    progress = context.user_data.get("ltr_main_progress", 0)
    tasks.append({
        "word_id": word_id,
        "stage": stage,
        "due_after": progress + delay_main,
    })


def _ltr_progress_header(context) -> str:
    word_ids = context.user_data.get("ltr_words", [])
    total = len(word_ids) or 1
    pos = context.user_data.get("ltr_current_word_pos", context.user_data.get("ltr_main_index", 1))
    bar = progress_bar(pos, total)
    return f"📍 کلمه {pos} از {total}  [{bar}]\n"

def _due_delayed_task(context):
    tasks = context.user_data.get("ltr_delayed_tasks", [])
    if not isinstance(tasks, list):
        tasks = []
        context.user_data["ltr_delayed_tasks"] = tasks

    progress = context.user_data.get("ltr_main_progress", 0)
    tasks.sort(key=lambda t: t.get("due_after", 0) if isinstance(t, dict) else 0)

    for i, task in enumerate(tasks):
        if isinstance(task, dict) and task.get("due_after", 0) <= progress:
            return tasks.pop(i)

    return None

async def _finalize_ltr_word(query, context, word_id: int):
    user_id = query.from_user.id
    results = context.user_data.get("ltr_word_results", {}).get(word_id, [])
    fsrs.review_ltr(user_id, word_id, results)
    correct_count = sum(1 for r in results if r)
    if results and all(results):
        db.record_activity(user_id, 20)
    elif results:
        db.record_activity(user_id, 5 * correct_count)
    if any(not r for r in results):
        wrong_list = context.user_data.setdefault("ltr_wrong_in_session", [])
        if word_id not in wrong_list:
            wrong_list.append(word_id)
        db.add_pending_review(user_id, word_id)
    else:
        db.clear_pending_reviews(user_id, [word_id])

async def start_study_session(query, context, lesson_id: int):
    user_id = query.from_user.id

    weak_words = db.get_weak_words_by_lesson(user_id, lesson_id, limit=3)
    remaining = max(0, 10 - len(weak_words))
    new_words = db.get_new_word_objects(user_id=user_id, lesson_id=lesson_id, limit=remaining)

    all_words = weak_words + new_words
    if not all_words:
        await render(query, "🎉 همه کلمات این درس را یاد گرفته‌ای!", reply_markup=back_inline_keyboard())
        return

    weak_count = len(weak_words)
    new_count = len(new_words)

    context.user_data["ltr_words"] = [w.id for w in all_words]
    context.user_data["ltr_main_index"] = 0
    context.user_data["ltr_main_progress"] = 0
    context.user_data["ltr_delayed_tasks"] = []
    context.user_data["ltr_retry_stage"] = None
    context.user_data["ltr_lesson_id"] = lesson_id
    context.user_data["ltr_wrong_in_session"] = []
    context.user_data["ltr_word_results"] = {}
    context.user_data["ltr_round"] = 1
    context.user_data.pop("ltr_round2_started", None)

    # پاک‌سازی کلیدهای نسخه قبلی
    context.user_data.pop("ltr_index", None)
    context.user_data.pop("ltr_delayed_1", None)
    context.user_data.pop("ltr_delayed_2", None)

    msg = (
        f"📚 <b>درس آماده است!</b>\n"
        f"🔴 مرور کلمات سخت: {weak_count}\n"
        f"🆕 کلمات جدید: {new_count}\n"
        f"📝 مجموع: {len(all_words)} کلمه\n"
        f"هر کلمه چند بار تست می‌شود:\n"
        f"۱️⃣ بلافاصله (آلمانی→فارسی)\n"
        f"۲️⃣ کمی بعد (فارسی→آلمانی)\n"
        f"۳️⃣ کمی بعدتر (آرتیکل/جای خالی/معنی)\n"
        f"شروع می‌کنیم؟ 🚀"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 شروع!", callback_data="ltr_start")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"lesson_{lesson_id}")],
    ])

    await render(query, msg, reply_markup=kb)


async def handle_ltr_start(query, context, suffix=None):
    if context.user_data.get("ltr_round", 1) == 2 and not context.user_data.get("ltr_round2_started"):
        context.user_data["ltr_word_results"] = {}
        context.user_data["ltr_round2_started"] = True

    await _advance_ltr(query, context)


async def handle_ltr_exit(query, context, suffix=None):
    await _show_ltr_summary(query, context)


async def _show_ltr_intro(query, context, is_retry: bool = False):
    word_id = context.user_data.get("ltr_current_word_id")
    word = db.get_word_by_id(word_id) if word_id else None

    if not word:
        await _advance_ltr(query, context)
        return

    context.user_data["ltr_state"] = "intro"
    context.user_data["current_tts_text"] = word.display_german

    word_ids = context.user_data.get("ltr_words", [])
    total = len(word_ids) or 1
    pos = context.user_data.get("ltr_current_word_pos", context.user_data.get("ltr_main_index", 1))

    notice = "🔄 <b>مرور مجدد</b>\n" if is_retry else ""
    bar = progress_bar(pos, total)
    msg = f"{notice}📖 <b>کلمه {pos} از {total}</b>  [{bar}]\n"
    msg += f"🇩🇪 <b>{esc(word.display_german)}</b>\n"
    msg += f"🇮🇷 {esc(word.persian)}\n"

    if word.english_meaning:
        msg += f"🇬🇧 {esc(word.english_meaning)}\n"
    if word.extra_forms_line:
        msg += f"📖 {esc(word.extra_forms_line)}\n"
    if word.collocation_line:
        msg += f"🔗 {esc(word.collocation_line)}\n"
    if word.example_de:
        msg += f"\n📝 {esc(word.example_de)}\n"
    if word.example_fa:
        msg += f"🇮🇷 <i>{esc(word.example_fa)}</i>\n"

    await render(query, msg, reply_markup=_ltr_intro_keyboard())


async def handle_ltr_ready(query, context, suffix=None):
    retry_stage = context.user_data.pop("ltr_retry_stage", None)
    word_id = context.user_data.get("ltr_current_word_id")

    if retry_stage and word_id:
        if retry_stage == "test_immediate":
            await _show_ltr_test_immediate(query, context, is_retry=True)
        elif retry_stage == "test_delayed_1":
            await _show_ltr_test_delayed_1(query, context, is_retry=True)
        elif retry_stage == "test_delayed_2":
            await _show_ltr_test_delayed_2(query, context, is_retry=True)
        else:
            await _show_ltr_test_immediate(query, context, is_retry=True)
    else:
        await _show_ltr_test_immediate(query, context)


async def _show_ltr_test_immediate(query, context, is_retry: bool = False):
    word_id = context.user_data.get("ltr_current_word_id")
    word = db.get_word_by_id(word_id)

    if not word:
        await _advance_ltr(query, context)
        return

    context.user_data["ltr_state"] = "test_immediate"
    context.user_data.pop("ltr_answer_lock", None)

    from handlers.quiz_handlers import _get_smart_wrong_persian_options
    wrongs = _get_smart_wrong_persian_options(word, count=3)

    correct = str(word.persian or "").strip()
    options = _make_ltr_options(correct, wrongs, total=4, min_options=1)
    if not options:
        options = [correct]

    context.user_data["ltr_correct_answer"] = correct
    context.user_data["ltr_correct_index"] = options.index(correct)
    context.user_data["current_tts_text"] = word.display_german

    header = "🔄 <b>تست مجدد</b>\n" if is_retry else ""
    msg = f"{header}1️⃣ <b>تست فوری</b>\n"
    msg += f"🇩🇪 <b>{esc(word.display_german)}</b>\n"
    msg += "معنی این کلمه چیست؟"

    await render(query, msg, reply_markup=_ltr_answer_keyboard(options))


async def _show_ltr_test_delayed_1(query, context, is_retry: bool = False):
    word_id = context.user_data.get("ltr_current_word_id")
    word = db.get_word_by_id(word_id)

    if not word:
        await _advance_ltr(query, context)
        return

    context.user_data["ltr_state"] = "test_delayed_1"
    context.user_data.pop("ltr_answer_lock", None)

    wrongs = _ltr_wrong_display_german_options(word, count=3)
    correct = str(word.display_german or "").strip()

    options = _make_ltr_options(correct, wrongs, total=4, min_options=1)
    if not options:
        options = [correct]

    context.user_data["ltr_correct_answer"] = correct
    context.user_data["ltr_correct_index"] = options.index(correct)

    header = "🔄 <b>تست مجدد</b>\n" if is_retry else ""
    msg = f"{header}2️⃣ <b>تست تأخیری</b>\n"
    msg += f"🇮🇷 <b>{esc(word.persian)}</b>\n"
    msg += "معادل آلمانی چیست؟"

    await render(query, msg, reply_markup=_ltr_answer_keyboard(options))


async def _show_ltr_test_delayed_2(query, context, is_retry: bool = False):
    word_id = context.user_data.get("ltr_current_word_id")
    word = db.get_word_by_id(word_id)

    if not word:
        await _advance_ltr(query, context)
        return

    context.user_data["ltr_state"] = "test_delayed_2"
    context.user_data.pop("ltr_answer_lock", None)

    header = "🔄 <b>تست مجدد</b>\n" if is_retry else ""
    options = None
    correct = None
    msg = ""

    article = (word.article or "").strip().lower()

    if word.word_type == "Noun" and article in ("der", "die", "das"):
        options = ["der", "die", "das"]
        random.shuffle(options)
        correct = article

        msg = f"{header}3️⃣ <b>تست نهایی</b>\n"
        msg += "🎯 آرتیکل صحیح:\n"
        msg += f"______ <b>{esc(word.german)}</b>\n"
        msg += f"🇮🇷 {esc(word.persian)}"

    else:
        cloze = None
        if word.example_de:
            from quiz_service import QuizService
            cloze = QuizService.create_cloze_quiz(word.german, word.persian, word.example_de)

        if cloze:
            from handlers.quiz_handlers import _get_smart_wrong_german_options
            correct = cloze["correct_answer"]
            wrongs = _get_smart_wrong_german_options(word, count=3)
            options = _make_ltr_options(correct, wrongs, total=4, min_options=1)

            if options:
                msg = f"{header}3️⃣ <b>تست نهایی</b>\n"
                msg += f"📝 {cloze['question']}"

        if not options:
            from handlers.quiz_handlers import _get_smart_wrong_persian_options
            correct = word.persian
            wrongs = _get_smart_wrong_persian_options(word, count=3)
            options = _make_ltr_options(correct, wrongs, total=4, min_options=1)

            if options:
                msg = f"{header}3️⃣ <b>تست نهایی</b>\n"
                msg += f"🇩🇪 <b>{esc(word.display_german)}</b>\n"
                msg += "معنی این کلمه چیست؟"
                context.user_data["current_tts_text"] = word.display_german

    correct = str(correct or "").strip()
    if not options or not correct or correct not in options:
        await _finalize_ltr_word(query, context, word_id)
        await _advance_ltr(query, context)
        return

    context.user_data["ltr_correct_answer"] = correct
    context.user_data["ltr_correct_index"] = options.index(correct)

    await render(query, msg, reply_markup=_ltr_answer_keyboard(options))


async def handle_ltr_answer(query, context, suffix: str):
    try:
        chosen = int(suffix)
    except ValueError:
        return
    correct_idx = context.user_data.get("ltr_correct_index", -1)
    is_correct = (chosen == correct_idx)
    state = context.user_data.get("ltr_state", "")
    word_id = context.user_data.get("ltr_current_word_id")
    lock_value = f"{word_id}:{state}"
    if context.user_data.get("ltr_answer_lock") == lock_value:
        try:
            await query.answer()
        except Exception:
            pass
        return
    context.user_data["ltr_answer_lock"] = lock_value

    if not word_id or state not in {"test_immediate", "test_delayed_1", "test_delayed_2"}:
        try:
            await query.answer("⚠️ جلسه منقضی شده. /menu", show_alert=True)
        except Exception:
            pass
        return
    word_results = context.user_data.setdefault("ltr_word_results", {})
    word_results.setdefault(word_id, []).append(is_correct)
    if is_correct:
        try:
            await query.answer("✅ درست!", show_alert=False)
        except Exception:
            pass
    else:
        correct_ans = context.user_data.get("ltr_correct_answer", "?")
        try:
            await query.answer(f"❌ جواب: {correct_ans}", show_alert=True)
        except Exception:
            pass
    if state == "test_immediate":
        if is_correct:
            _schedule_delayed_task(context, word_id, "test_delayed_1", delay_main=2)
            await _advance_ltr(query, context)
        else:
            context.user_data["ltr_retry_stage"] = "test_immediate"
            await _show_ltr_intro(query, context, is_retry=True)
    elif state == "test_delayed_1":
        if is_correct:
            _schedule_delayed_task(context, word_id, "test_delayed_2", delay_main=3)
            await _advance_ltr(query, context)
        else:
            context.user_data["ltr_retry_stage"] = "test_delayed_1"
            await _show_ltr_intro(query, context, is_retry=True)
    elif state == "test_delayed_2":
        await _finalize_ltr_word(query, context, word_id)
        await _advance_ltr(query, context)

async def _advance_ltr(query, context):
    task = _due_delayed_task(context)

    if task:
        word_id = task.get("word_id")
        stage = task.get("stage")
        word = db.get_word_by_id(word_id) if word_id else None

        if not word:
            await _advance_ltr(query, context)
            return

        context.user_data["ltr_current_word_id"] = word_id
        context.user_data["ltr_retry_stage"] = None

        if stage == "test_delayed_1":
            await _show_ltr_test_delayed_1(query, context)
        else:
            await _show_ltr_test_delayed_2(query, context)

        return

    word_ids = context.user_data.get("ltr_words", [])
    main_index = context.user_data.get("ltr_main_index", 0)

    if main_index < len(word_ids):
        word_id = word_ids[main_index]

        context.user_data["ltr_main_index"] = main_index + 1
        context.user_data["ltr_main_progress"] = context.user_data.get("ltr_main_progress", 0) + 1
        context.user_data["ltr_current_word_id"] = word_id
        context.user_data["ltr_current_word_pos"] = context.user_data["ltr_main_progress"]
        context.user_data["ltr_state"] = "intro"
        context.user_data["ltr_retry_stage"] = None

        await _show_ltr_intro(query, context)
        return

    tasks = context.user_data.get("ltr_delayed_tasks", [])
    if isinstance(tasks, list) and tasks:
        tasks.sort(key=lambda t: t.get("due_after", 0) if isinstance(t, dict) else 0)

        while tasks:
            task = tasks.pop(0)
            if not isinstance(task, dict):
                continue

            word_id = task.get("word_id")
            stage = task.get("stage")
            word = db.get_word_by_id(word_id) if word_id else None

            if not word:
                continue

            context.user_data["ltr_current_word_id"] = word_id
            context.user_data["ltr_retry_stage"] = None

            if stage == "test_delayed_1":
                await _show_ltr_test_delayed_1(query, context)
            else:
                await _show_ltr_test_delayed_2(query, context)

            return

    await _finish_ltr_session(query, context)


async def _finish_ltr_session(query, context):
    wrong_ids = list(dict.fromkeys(context.user_data.get("ltr_wrong_in_session", [])))

    context.user_data["ltr_delayed_tasks"] = []
    context.user_data["ltr_retry_stage"] = None

    round_num = context.user_data.get("ltr_round", 1)

    if wrong_ids and round_num < 2:
        context.user_data["ltr_words"] = wrong_ids
        context.user_data["ltr_main_index"] = 0
        context.user_data["ltr_main_progress"] = 0
        context.user_data["ltr_wrong_in_session"] = []
        context.user_data["ltr_round"] = 2
        context.user_data.pop("ltr_round2_started", None)

        msg = (
            f"🔄 <b>راند دوم!</b>\n"
            f"{len(wrong_ids)} کلمه را اشتباه زدی.\n"
            f"دوباره تمرین می‌کنیم! 💪"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 شروع راند ۲", callback_data="ltr_start")],
            [InlineKeyboardButton("🏁 فعلاً بس است", callback_data="ltr_summary")],
        ])

        await render(query, msg, reply_markup=kb)
    else:
        await _show_ltr_summary(query, context)


async def handle_ltr_summary(query, context, suffix=None):
    await _show_ltr_summary(query, context)


async def _show_ltr_summary(query, context):
    results = context.user_data.get("ltr_word_results", {})
    lesson_id = context.user_data.get("ltr_lesson_id")

    total = len(results)
    perfect = sum(1 for r in results.values() if all(r))
    partial = sum(1 for r in results.values() if any(r) and not all(r))
    failed = total - perfect - partial
    accuracy = (perfect / total * 100) if total > 0 else 0

    msg = (
        f"🏁 <b>جلسه تمام شد!</b>\n"
        f"📊 <b>خلاصه:</b>\n"
        f"✅ کامل درست: {perfect}\n"
        f"⚠️ نسبی: {partial}\n"
        f"❌ نیاز به تمرین: {failed}\n"
        f"🎯 دقت: {accuracy:.0f}%\n"
    )

    if total == 0:
        msg += "📭 موردی ثبت نشد."
    elif failed > 0:
        msg += f"💡 {failed} کلمه سخت داری. فردا اول از آن‌ها شروع می‌کنم!"
    else:
        msg += "🌟 عالی بود! همه کلمات را خوب یاد گرفتی!"

    for key in [
        "ltr_words", "ltr_index", "ltr_lesson_id", "ltr_wrong_in_session",
        "ltr_word_results", "ltr_current_word_id",
        "ltr_state", "ltr_correct_answer", "ltr_correct_index",
        "ltr_delayed_1", "ltr_delayed_2", "ltr_round",
        "ltr_main_index", "ltr_main_progress", "ltr_delayed_tasks",
        "ltr_retry_stage", "ltr_current_word_pos", "ltr_round2_started",
    ]:
        context.user_data.pop(key, None)

    kb_rows = []

    if lesson_id:
        kb_rows.extend([
            [InlineKeyboardButton("📚 ۱۰ کلمه بعدی", callback_data=f"study_lesson:{lesson_id}")],
            [InlineKeyboardButton("🎴 فلش‌کارت این درس", callback_data=f"flashcard_lesson:{lesson_id}")],
            [InlineKeyboardButton("🤖 کوییز این درس", callback_data=f"quiz_from_lesson:{lesson_id}")],
        ])

    kb_rows.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")])

    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb_rows))