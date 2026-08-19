"""Flashcard session management and rendering."""

import asyncio
import logging
import time
from collections import deque
from typing import Optional, Set

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
from models import Word
from services import db, fsrs, llm
from ui import _bold_word_in_sentence, back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)

_pending_examples: dict = {}  # key -> timestamp


class FlashcardSessionManager:
    """Manages flashcard session state and queue."""

    def __init__(self, context):
        self.context = context
        self.user_data = context.user_data

    def initialize(
        self,
        lesson_id: Optional[int] = None,
        only_new: bool = False,
        only_due: bool = False,
        hard_only: bool = False,
    ) -> None:
        """Initialize flashcard session with settings."""
        self.user_data["active_lesson_id"] = lesson_id
        self.user_data["flashcard_only_new"] = only_new
        self.user_data["flashcard_only_due"] = only_due
        self.user_data["flashcard_hard_only"] = hard_only
        self.user_data["flashcard_skipped_ids"] = set()
        self.user_data["flashcard_again_counts"] = {}

    def load_words(
        self,
        user_id: int,
        limit: int = config.FLASHCARD_QUEUE_LIMIT,
    ) -> list[Word]:
        """Load words based on session settings."""
        hard_only = self.user_data.get("flashcard_hard_only", False)
        only_due = self.user_data.get("flashcard_only_due", False)
        only_new = self.user_data.get("flashcard_only_new", False)
        lesson_id = self.user_data.get("active_lesson_id")

        if hard_only:
            return db.words.get_hard_due(
                user_id,
                limit=limit,
            )
        elif only_due:
            return db.words.get_due(
                user_id,
                limit=limit,
                lesson_id=lesson_id,
            )
        else:
            return fsrs.get_review_cards(
                user_id,
                limit=limit,
                lesson_id=lesson_id,
                include_new=True,
                new_limit=config.FLASHCARD_NEW_LIMIT,
                only_new=only_new,
            )

    def set_queue(self, words: list[Word]) -> None:
        """Set the flashcard queue from word list."""
        self.user_data["flashcard_queue"] = deque([w.id for w in words[1:]])

    def get_current_word_id(self) -> Optional[int]:
        """Get current flashcard word ID."""
        fc_data = self.user_data.get("current_flashcard", {})
        return fc_data.get("word_id") if fc_data else None

    def set_current_word(self, word_id: int) -> None:
        """Set current flashcard word."""
        self.user_data["current_flashcard"] = {"word_id": word_id}
        self.user_data.pop("flashcard_rate_lock", None)

    def add_to_skipped(self, word_id: int) -> None:
        """Add word to skipped set."""
        skipped = self.user_data.setdefault("flashcard_skipped_ids", set())
        skipped.add(word_id)

    def get_skipped_ids(self) -> Set[int]:
        """Get set of skipped word IDs."""
        return self.user_data.get("flashcard_skipped_ids", set())

    def pop_queue(self) -> Optional[int]:
        """Pop next word ID from queue."""
        queue = self.user_data.get("flashcard_queue")
        if not isinstance(queue, deque):
            queue = deque(queue or [])
            self.user_data["flashcard_queue"] = queue

        return queue.popleft() if queue else None

    def get_remaining_count(self) -> int:
        """Get remaining cards count."""
        queue = self.user_data.get("flashcard_queue")
        return (len(queue) + 1) if isinstance(queue, deque) else 1

    def clear_session(self) -> None:
        """Clear all flashcard session data."""
        keys_to_clear = [
            "current_flashcard",
            "flashcard_queue",
            "current_tts_text",
            "flashcard_skipped_ids",
            "flashcard_hard_only",
            "flashcard_only_new",
            "flashcard_only_due",
            "active_lesson_id",
            "fsrs_guide_shown",
            "flashcard_again_counts",
        ]
        for key in keys_to_clear:
            self.user_data.pop(key, None)

def _flashcard_front_keyboard(
    word: Word, quick_rate: bool = False
) -> InlineKeyboardMarkup:
    """کیبورد سمت جلوی کارت.
    با quick_rate، ردیف ارزیابی مستقیم هم نمایش داده می‌شود تا کاربرِ
    مطمئن بدون فلیپ، با یک tap ثبت کند."""
    rows = [
        [
            InlineKeyboardButton(
                "👀 نمایش معنی", callback_data=f"flip_card:{word.id}"
            )
        ],
    ]
    if quick_rate:
        rows.append(
            [
                InlineKeyboardButton(
                    "😵 Again", callback_data=f"rate_card:{word.id}:1"
                ),
                InlineKeyboardButton(
                    "😬 Hard", callback_data=f"rate_card:{word.id}:2"
                ),
                InlineKeyboardButton(
                    "🙂 Good", callback_data=f"rate_card:{word.id}:3"
                ),
                InlineKeyboardButton(
                    "😎 Easy", callback_data=f"rate_card:{word.id}:4"
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:front"),
            InlineKeyboardButton(
                "⏭️ رد شدن", callback_data=f"skip_flashcard:{word.id}"
            ),
        ]
    )
    rows.append(
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    )
    return InlineKeyboardMarkup(rows)

def _flashcard_rate_keyboard(word: Word) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔊 تلفظ", callback_data="speak_current:back")],
            [
                InlineKeyboardButton(
                    "😵 Again", callback_data=f"rate_card:{word.id}:1"
                ),
                InlineKeyboardButton("😬 Hard", callback_data=f"rate_card:{word.id}:2"),
                InlineKeyboardButton("🙂 Good", callback_data=f"rate_card:{word.id}:3"),
                InlineKeyboardButton("😎 Easy", callback_data=f"rate_card:{word.id}:4"),
            ],
        ]
    )

async def start_flashcard_due(query, context):
    await start_flashcard_session(query, context, only_due=True)


async def start_flashcard_hard(query, context):
    await start_flashcard_session(query, context, hard_only=True)

async def _send_or_edit(query, update, text: str, reply_markup):
    """Send or edit message based on context."""
    await render(query or update, text, reply_markup=reply_markup)


def _get_level_for_context(context, user_id: int) -> str:
    """Get user's preferred level from context or database."""
    lesson_id = (
        context.user_data.get("active_lesson_id")
        or context.user_data.get("ltr_lesson_id")
        or context.user_data.get("study_lesson_id")
    )

    if lesson_id:
        level = db.books.get_level_by_lesson(lesson_id)
        if level:
            return level

    settings = db.users.get_settings(user_id)
    return settings.get("preferred_level", "A1")


def _should_quick_rate(user_id: Optional[int], word_id: int) -> bool:
    """شرط نمایش دکمه‌های ارزیابی مستقیم روی سمت جلوی کارت:
    ۱) flag تنظیمات FLASHCARD_QUICK_RATE روشن باشد
    ۲) کلمه قبلاً دیده شده باشد (رکورد word_stats داشته باشد)
    کلمات کاملاً جدید همچنان مسیر فلیپ اجباری را دارند."""
    if not config.FLASHCARD_QUICK_RATE or not user_id:
        return False
    return db.words.get_stats_full(user_id, word_id) is not None

async def start_flashcard_session(
    update,
    context,
    lesson_id: Optional[int] = None,
    only_new: bool = False,
    only_due: bool = False,
    hard_only: bool = False,
):
    """Start a new flashcard session."""
    query = getattr(update, "callback_query", None)
    if query is None and hasattr(update, "data"):
        query = update

    user_id = query.from_user.id if query else update.effective_user.id

    # Initialize session manager
    session = FlashcardSessionManager(context)
    session.initialize(
        lesson_id=lesson_id,
        only_new=only_new,
        only_due=only_due,
        hard_only=hard_only,
    )

    # Load words
    words = session.load_words(user_id)

    if not words:
        if hard_only:
            msg = "🎉 هیچ کلمه‌ی سختِ معوقی نداری!"
        elif only_due:
            msg = "🎉 آفرین! هیچ کلمه‌ای برای مرور نداری!"
        elif only_new:
            msg = "🎉 همه کلمات جدید این درس را قبلاً دیده‌ای!"
        else:
            msg = "🎉 آفرین! هیچ کلمه‌ای برای مرور نداری!"

        await _send_or_edit(query, update, msg, back_inline_keyboard())
        return

    # Set queue and show first card
    session.set_queue(words)
    await _render_flashcard_front(query, update, context, words[0])


async def _render_flashcard_front(
    query, update, context, word: Word, notice: Optional[str] = None
):
    """Render flashcard front side."""
    if query:
        user_id = query.from_user.id
    elif hasattr(update, "effective_user") and update.effective_user:
        user_id = update.effective_user.id
    else:
        user_id = None

    # Set current word
    session = FlashcardSessionManager(context)
    session.set_current_word(word.id)
    quick_rate = _should_quick_rate(user_id, word.id)

    # Example priority:
    # 1. Saved example from words table
    # 2. Cached LLM example from llm_examples table
    # 3. Background generation, no blocking
    example = None

    if word.example_de:
        example = {
            "de": word.example_de,
            "fa": word.example_fa,
        }
    else:
        level = _get_level_for_context(context, user_id) if user_id else "A1"
        example = db.learning.get_llm_example(word.id, level)

        if not example and user_id and llm.is_available():
            pending_key = (word.id, level)
            now = time.time()

            # حذف entry های قدیمی (بیشتر از ۵ دقیقه)
            global _pending_examples
            _pending_examples = {
                k: v for k, v in _pending_examples.items() if now - v < 300
            }
            if pending_key not in _pending_examples:
                _pending_examples[pending_key] = now
                asyncio.create_task(
                    _generate_and_cache_example(
                        word_id=word.id,
                        german=word.german,
                        article=word.article,
                        meaning=word.persian,
                        level=level,
                        pending_key=pending_key,
                    )
                )

    context.user_data["current_flashcard"]["example"] = example

    # Build message
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
            speak_text = example["de"]
        else:
            parts.append(f"🇩🇪 <b>{esc(word.display_german)}</b>")
    else:
        parts.append(f"🇩🇪 <b>{esc(word.display_german)}</b>")

    context.user_data["current_tts_text"] = speak_text

    await _send_or_edit(
        query,
        update,
        "\n".join(parts),
        _flashcard_front_keyboard(word, quick_rate=quick_rate),
    )


async def handle_flip_card(query, context, suffix: str = None):
    """Handle flip card action."""
    lock_key = "flashcard_flip_lock"

    if context.user_data.get(lock_key):
        try:
            await query.answer()
        except Exception:
            pass
        return

    context.user_data[lock_key] = True

    try:
        try:
            word_id = int(suffix) if suffix else int(query.data.split(":")[1])
        except (ValueError, IndexError):
            await render(query, "❌ کارت نامعتبر.", reply_markup=back_inline_keyboard())
            return

        current = context.user_data.get("current_flashcard") or {}
        if current.get("word_id") != word_id:
            try:
                await query.answer("⚠️ این کارت منقضی شده.", show_alert=True)
            except Exception:
                pass
            return

        word = await run_db(db.words.get_by_id, word_id)
        if not word:
            await render(
                query, "❌ کلمه پیدا نشد.", reply_markup=back_inline_keyboard()
            )
            return

        fc_data = context.user_data.get("current_flashcard", {}) or {}
        example = fc_data.get("example")
        fc_data["flipped"] = True
        context.user_data["current_flashcard"] = fc_data
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
            context.user_data["fsrs_guide_shown"] = True
        context.user_data["current_tts_text"] = speak_text

        await render(query, msg, reply_markup=_flashcard_rate_keyboard(word))

    finally:
        context.user_data.pop(lock_key, None)


async def handle_rate_card(query, context, suffix: str = None):
    """Handle card rating action."""
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

    lock_key = "flashcard_rate_lock"
    lock_value = str(word_id)

    if context.user_data.get(lock_key) == lock_value:
        try:
            await query.answer()
        except Exception:
            pass
        return

    current = context.user_data.get("current_flashcard") or {}
    if current.get("word_id") != word_id:
        try:
            await query.answer("⚠️ این کارت منقضی شده.", show_alert=True)
        except Exception:
            pass
        return

    context.user_data["flashcard_rate_lock"] = lock_value

    try:
        _, interval_days = await run_db(
            fsrs.review_flashcard,
            user_id,
            word_id,
            grade,
        )
        requeued = False

        # اگر Again بود، همان جلسه دوباره وارد صف شود
        if grade == 1:
            again_counts = context.user_data.setdefault("flashcard_again_counts", {})
            again_counts[word_id] = again_counts.get(word_id, 0) + 1

            # حداکثر ۲ بار تکرار فوری در همان جلسه
            if again_counts[word_id] <= 2:
                queue = context.user_data.get("flashcard_queue")
                if not isinstance(queue, deque):
                    queue = deque(queue or [])

                queue.appendleft(word_id)
                context.user_data["flashcard_queue"] = queue
                requeued = True

        # ثبت مهارت فلش‌کارت
        db.learning.record_skill(user_id, word_id, "flashcard", grade >= 2)
        db.users.record_activity(user_id, 5)

        grade_names = {1: "😵 Again", 2: "😬 Hard", 3: "🙂 Good", 4: "😎 Easy"}

        if grade == 1:
            if requeued:
                notice = "😵 Again ثبت شد — همین جلسه دوباره می‌آید."
            else:
                notice = "😵 Again ثبت شد — مرور بعدی: کمی بعد."
        elif interval_days <= 0:
            notice = (
                f"✅ {grade_names.get(grade, grade)} ثبت شد (مرور بعدی: کمتر از ۱ روز)"
            )
        elif interval_days == 1:
            notice = f"✅ {grade_names.get(grade, grade)} ثبت شد (مرور بعدی: ۱ روز)"
        else:
            notice = f"✅ {grade_names.get(grade, grade)} ثبت شد (مرور بعدی: {interval_days} روز)"
        if not current.get("flipped"):
            rated_word = db.words.get_by_id(word_id)
            if rated_word and rated_word.persian:
                notice += f"\n📌 {rated_word.display_german} = {rated_word.persian}"
        await _go_next_flashcard(query, context, notice=notice)

    finally:
        context.user_data.pop("flashcard_rate_lock", None)


async def handle_next_flashcard(query, context, suffix: str = None):
    """Handle next flashcard action."""
    await _go_next_flashcard(query, context, notice=None)


async def handle_skip_flashcard(query, context, suffix: str = None):
    """Handle skip flashcard action."""
    # ✅ Lock: جلوگیری از double-tap
    lock_key = "flashcard_skip_lock"
    if context.user_data.get(lock_key):
        try:
            await query.answer()
        except Exception:
            pass
        return
    context.user_data[lock_key] = True

    try:
        fc = context.user_data.get("current_flashcard") or {}
        word_id = fc.get("word_id")
        if word_id:
            session = FlashcardSessionManager(context)
            session.add_to_skipped(word_id)
        await _go_next_flashcard(query, context, notice="⏭️ رد شد")
    finally:
        context.user_data.pop(lock_key, None)


async def _go_next_flashcard(query, context, notice: Optional[str] = None):
    """Go to next flashcard or finish session."""
    user_id = query.from_user.id
    session = FlashcardSessionManager(context)

    # Try to get next from queue
    word_id = session.pop_queue()

    while word_id is not None:
        word = await run_db(db.words.get_by_id, word_id)
        if word:
            await _render_flashcard_front(query, None, context, word, notice=notice)
            return
        word_id = session.pop_queue()

    # Queue empty - check if hard-only mode
    if context.user_data.get("flashcard_hard_only", False):
        user_id = query.from_user.id
        last_word_id = session.get_current_word_id()
        skipped = session.get_skipped_ids()

        exclude_ids = {last_word_id} if last_word_id else set()
        exclude_ids.update(skipped)

        words = await run_db(
            db.words.get_hard_due,
            user_id,
            limit=config.FLASHCARD_QUEUE_LIMIT,
            exclude_ids=exclude_ids,
        )

        if words:
            session.set_queue(words)
            await _render_flashcard_front(query, None, context, words[0], notice=notice)
            return

        session.clear_session()
        await render(
            query,
            "🎉 مرور کلمات سخت امروز تمام شد! آفرین! 🔥",
            reply_markup=back_inline_keyboard(),
        )
        return

    # Refill queue
    session.clear_session()
    if context.user_data.get("flashcard_only_new"):
        msg = "🎉 کلمات جدید این درس تمام شد!"
    elif context.user_data.get("flashcard_only_due"):
        msg = "🎉 مرور امروز تمام شد! آفرین!"
    elif context.user_data.get("flashcard_hard_only"):
        msg = "🎉 مرور کلمات سخت تمام شد! 🔥"
    else:
        msg = "🎉 آفرین! همه کلمات مرور شدند!"
    await render(query, msg, reply_markup=back_inline_keyboard())


__all__ = [
    "FlashcardSessionManager",
    "start_flashcard_session",
    "handle_flip_card",
    "handle_rate_card",
    "handle_next_flashcard",
    "handle_skip_flashcard",
    "_render_flashcard_front",
    "_generate_and_cache_example",
]


async def _generate_and_cache_example(
    word_id: int,
    german: str,
    article: Optional[str],
    meaning: str,
    level: str,
    pending_key: tuple,
):
    """Generate LLM example in background and cache it."""
    try:
        example = await llm.generate_contextual_example(
            german,
            article=article,
            meaning=meaning,
            level=level,
        )

        if example and example.get("de"):
            db.learning.save_llm_example(
                word_id=word_id,
                level=level,
                example_de=example["de"],
                example_fa=example.get("fa"),
            )
            logger.info("مثال LLM برای word_id=%s ذخیره شد", word_id)

    except Exception as e:
        logger.warning("خطا در تولید مثال پس‌زمینه: %s", e)

    finally:
        _pending_examples.pop(pending_key, None)
