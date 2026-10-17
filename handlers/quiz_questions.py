"""Quiz word sourcing, question generation and optional background enrichment."""

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
import config
from models import Word
from option_generator import get_wrong_options
from services import db, llm, quiz_service, run_db

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task] = set()
_pending_quiz_examples: set[int] = set()


def _spawn_background(coro):
    """اجرای تسک در پس‌زمینه بدون بلاک کردن handler."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _fetch_words_by_source(
    user_id: int,
    lesson_id: Optional[int],
    source_filter: Optional[str],
    exclude_ids: set,
    limit: int = 100,
) -> Optional[List[Word]]:
    """منطق مشترک گرفتن کلمات بر اساس source_filter."""
    if source_filter == "weak":
        return await run_db(
            db.words.get_weak,
            user_id,
            limit=limit,
            lesson_id=lesson_id,
            exclude_ids=exclude_ids,
        )
    if source_filter == "due":
        return await run_db(
            db.words.get_due,
            user_id,
            limit=limit,
            lesson_id=lesson_id,
            exclude_ids=exclude_ids,
        )
    if source_filter == "mistakes":
        return await run_db(
            db.words.get_mistake_words,
            user_id,
            limit=limit,
            lesson_id=lesson_id,
            exclude_ids=exclude_ids,
        )
    # ✅ جدید: فقط کلمات دیده‌شده
    if source_filter == "seen":
        return await run_db(
            db.words.get_seen_words,
            user_id,
            limit=limit,
            lesson_id=lesson_id,
            exclude_ids=exclude_ids,
        )
    return None  # → fallback


async def _get_word_for_quiz(user_id, lesson_id, source_filter, exclude_ids):
    words = await _fetch_words_by_source(user_id, lesson_id, source_filter, set(exclude_ids or []))
    if words is not None:
        return random.choice(words) if words else None
    return await run_db(db.words.get_random, lesson_id=lesson_id, exclude_ids=exclude_ids)


async def _get_noun_with_article(user_id, lesson_id, source_filter, exclude_ids):
    words = await _fetch_words_by_source(user_id, lesson_id, source_filter, set(exclude_ids or []))
    if words is not None:
        words = [w for w in words if w.article]
        return random.choice(words) if words else None
    nouns = await run_db(
        db.words.get_nouns_with_article,
        lesson_id=lesson_id,
        limit=100,
        exclude_ids=exclude_ids,
    )
    return random.choice(nouns) if nouns else None


async def _get_word_with_example(user_id, lesson_id, source_filter, exclude_ids):
    """
    برای کوییز cloze فقط کلمه‌ای را انتخاب کن که مثال داشته باشد.
    اگر در source_filter کلمه با مثال نبود، از کل کلمات دارای مثال استفاده کن.
    """
    words = await _fetch_words_by_source(user_id, lesson_id, source_filter, set(exclude_ids or []))

    if words is not None:
        candidates = [w for w in words if w.example_de]
        return random.choice(candidates) if candidates else None

    words = await run_db(
        db.words.get_with_examples,
        lesson_id=lesson_id,
        exclude_ids=exclude_ids,
    )

    return random.choice(words) if words else None


async def _ensure_example_background(word: Word, level: str, user_id: Optional[int] = None) -> None:
    """
    اگر کلمه مثال ندارد، در پس‌زمینه مثال LLM بساز و ذخیره کن.
    این تابع هرگز نباید کوییز را بلاک کند.

    ``user_id`` (optional) is used to enforce the per-user daily LLM
    example quota: if the user has already used their full
    ``LLM_DAILY_EXAMPLE_LIMIT`` for today, no LLM call is made.
    A successful save counts as one consumption.
    """
    if not word or not word.id:
        return

    if word.example_de:
        return

    if not llm.is_available():
        return

    if word.id in _pending_quiz_examples:
        return

    # ✅ بررسی سهمیه روزانه مثال پیش از فراخوانی LLM
    if user_id is not None:
        allowed = await run_db(db.learning.is_llm_action_allowed, user_id, "example")
        if not allowed:
            logger.info(
                "سهمیه روزانه مثال LLM برای user_id=%s تمام شد، تولید لغو شد",
                user_id,
            )
            return

    _pending_quiz_examples.add(word.id)

    try:
        example = await llm.generate_contextual_example(
            word.german,
            article=word.article,
            meaning=word.persian or "",
            level=level,
        )

        if example and example.get("de"):
            # ذخیره در جدول words برای استفاده‌های بعدی
            await run_db(
                db.words.execute,
                """
                UPDATE words
                SET example_de = ?, example_fa = ?
                WHERE id = ?
                """,
                (example.get("de"), example.get("fa"), word.id),
                commit=True,
            )

            # ذخیره در cache جداگانه LLM
            await run_db(
                db.learning.save_llm_example,
                word_id=word.id,
                level=level,
                example_de=example.get("de"),
                example_fa=example.get("fa"),
            )

            # فقط در صورت ذخیره موفق، سهمیه را مصرف کن
            if user_id is not None:
                await run_db(db.learning.increment_llm_usage, user_id, "example")

            logger.info("مثال پس‌زمینه برای word_id=%s ذخیره شد", word.id)

    except Exception as e:
        logger.warning(
            "خطا در تولید مثال پس‌زمینه برای word_id=%s: %s",
            word.id,
            e,
        )
    finally:
        _pending_quiz_examples.discard(word.id)


async def _gen_article(word: Word, user_id: int, level: str) -> Optional[Dict]:
    if not word.article:
        return None
    return quiz_service.create_article_quiz(word.article, word.german, word.persian)


async def _gen_meaning(word: Word, user_id: int, level: str) -> Optional[Dict]:
    """
    تولید سوال معنی به صورت local-first.
    اگر QUIZ_LLM_GENERATION فعال بود، فقط با timeout خیلی کم LLM را امتحان می‌کند.
    """
    wrong = await run_db(
        get_wrong_options,
        db,
        word,
        count=3,
        attr_getter=lambda w: w.persian,
    )

    local_quiz = quiz_service.create_meaning_quiz(
        word.display_german,
        word.persian,
        wrong,
    )

    if not config.QUIZ_LLM_GENERATION or not llm.is_available():
        return local_quiz

    try:
        llm_quiz = await asyncio.wait_for(
            llm.generate_quiz_question(
                word.display_german,
                word.persian,
                level=level,
                user_id=user_id,
                word_id=word.id,
            ),
            timeout=config.QUIZ_LLM_TIMEOUT_SECONDS,
        )

        return llm_quiz or local_quiz

    except Exception as e:
        logger.warning(
            "LLM meaning quiz timeout/fallback for word_id=%s: %s",
            word.id,
            e,
        )
        return local_quiz


async def _gen_reverse(word: Word, user_id: int, level: str) -> Optional[Dict]:
    """
    تولید سوال معکوس به صورت local-first.
    """
    correct_german = (
        word.display_german if (word.word_type == "Noun" and word.article) else word.german
    )

    wrong = await run_db(
        get_wrong_options,
        db,
        word,
        count=3,
        attr_getter=lambda w: w.display_german,
    )

    local_quiz = quiz_service.create_reverse_quiz(
        word.persian,
        correct_german,
        wrong,
    )

    if not config.QUIZ_LLM_GENERATION or not llm.is_available():
        return local_quiz

    try:
        llm_quiz = await asyncio.wait_for(
            llm.generate_reverse_quiz(
                correct_german,
                word.persian,
                level=level,
                user_id=user_id,
                word_id=word.id,
            ),
            timeout=config.QUIZ_LLM_TIMEOUT_SECONDS,
        )

        return llm_quiz or local_quiz

    except Exception as e:
        logger.warning(
            "LLM reverse quiz timeout/fallback for word_id=%s: %s",
            word.id,
            e,
        )
        return local_quiz


async def _gen_cloze(word: Word, user_id: int, level: str) -> Optional[Dict]:
    """
    تولید cloze فقط اگر مثال موجود باشد.
    اگر مثال نبود، LLM example در پس‌زمینه ساخته می‌شود، اما کوییز بلاک نمی‌شود.
    """
    ex_de = word.example_de

    if not ex_de:
        cached = await run_db(db.learning.get_llm_example, word.id, level)
        if cached:
            ex_de = cached.get("de")

    if not ex_de:
        if config.QUIZ_LLM_GENERATION and llm.is_available():
            _spawn_background(_ensure_example_background(word, level, user_id=user_id))
        return None

    base_cloze = quiz_service.create_cloze_quiz(
        word.german,
        word.persian,
        ex_de,
        article=word.article,
        word_type=word.word_type,
    )

    if not base_cloze:
        return None

    wrong = await run_db(
        get_wrong_options,
        db,
        word,
        count=3,
        attr_getter=lambda w: w.german,
    )

    return quiz_service.create_cloze_with_options(
        word.german,
        word.persian,
        ex_de,
        wrong,
        article=word.article,
        word_type=word.word_type,
    )


async def _gen_mixed(word: Word, user_id: int, level: str) -> Optional[Dict]:
    """
    تولید سوال ترکیبی با fallback هوشمند.
    اگر cloze آماده نبود، سریعاً به meaning/reverse/article برمی‌گردد.
    """
    possible_types = ["meaning", "reverse"]

    if word.word_type == "Noun" and word.article:
        possible_types.append("article")

    # ✅ بررسی example دیتابیس یا cached LLM example
    has_example = bool(word.example_de)
    if not has_example:
        cached = await run_db(db.learning.get_llm_example, word.id, level)
        has_example = bool(cached and cached.get("de"))

    if has_example:
        possible_types.append("cloze")

    random.shuffle(possible_types)

    for chosen_type in possible_types:
        quiz = None

        if chosen_type == "article":
            quiz = await _gen_article(word, user_id, level)
        elif chosen_type == "reverse":
            quiz = await _gen_reverse(word, user_id, level)
        elif chosen_type == "cloze":
            quiz = await _gen_cloze(word, user_id, level)
        else:
            quiz = await _gen_meaning(word, user_id, level)

        if quiz:
            return quiz

    # آخرین fallback
    return await _gen_meaning(word, user_id, level)


@dataclass
class QuizConfig:
    name: str
    display_name: str
    word_fetcher: Callable
    quiz_generator: Callable


QUIZ_REGISTRY: Dict[str, QuizConfig] = {
    "article": QuizConfig("article", "آرتیکل", _get_noun_with_article, _gen_article),
    "meaning": QuizConfig("meaning", "معنی", _get_word_for_quiz, _gen_meaning),
    "reverse": QuizConfig("reverse", "معکوس", _get_word_for_quiz, _gen_reverse),
    "cloze": QuizConfig("cloze", "جای خالی", _get_word_with_example, _gen_cloze),
    "mixed": QuizConfig("mixed", "ترکیبی", _get_word_for_quiz, _gen_mixed),  # ← جدید
}


async def close_background_tasks():
    """Cancel enrichment before the shared database is closed."""
    tasks = list(_background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _background_tasks.clear()
    _pending_quiz_examples.clear()
