import logging
import random
import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config
from models import Word
from services import db, fsrs, llm, quiz_service
from ui import back_inline_keyboard, esc, quiz_answer_keyboard, render

logger = logging.getLogger(__name__)


async def _get_word_for_quiz(
    user_id: int,
    lesson_id: Optional[int],
    source_filter: Optional[str],
    exclude_ids: Optional[Iterable[int]],
) -> Optional[Word]:
    exclude_ids = set(exclude_ids or [])

    if source_filter == "weak":
        words = db.get_weak_word_objects(user_id, limit=30, exclude_ids=exclude_ids)
        return random.choice(words) if words else None

    if source_filter == "due":
        words = db.get_due_word_objects(
            user_id, limit=30, lesson_id=lesson_id, exclude_ids=exclude_ids
        )
        return random.choice(words) if words else None

    return db.get_random_word_object(lesson_id=lesson_id, exclude_ids=exclude_ids)


async def _get_noun_with_article(
    user_id: int,
    lesson_id: Optional[int],
    source_filter: Optional[str],
    exclude_ids: Optional[Iterable[int]],
) -> Optional[Word]:
    exclude_ids = set(exclude_ids or [])

    if source_filter == "weak":
        words = [
            w
            for w in db.get_weak_word_objects(
                user_id, limit=100, exclude_ids=exclude_ids
            )
            if w.article
        ]
        return random.choice(words) if words else None

    if source_filter == "due":
        words = [
            w
            for w in db.get_due_word_objects(
                user_id, limit=100, lesson_id=lesson_id, exclude_ids=exclude_ids
            )
            if w.article
        ]
        return random.choice(words) if words else None

    nouns = db.words.get_nouns_with_article(limit=100, exclude_ids=exclude_ids)
    return random.choice(nouns) if nouns else None


async def _get_word_with_example(
    user_id: int,
    lesson_id: Optional[int],
    source_filter: Optional[str],
    exclude_ids: Optional[Iterable[int]],
) -> Optional[Word]:
    exclude_ids = set(exclude_ids or [])

    if source_filter == "weak":
        words = db.get_weak_word_objects(user_id, limit=100, exclude_ids=exclude_ids)
        return random.choice(words) if words else None

    if source_filter == "due":
        words = db.get_due_word_objects(
            user_id, limit=100, lesson_id=lesson_id, exclude_ids=exclude_ids
        )
        return random.choice(words) if words else None

    words = db.get_words_with_example_objects(
        lesson_id=lesson_id, exclude_ids=exclude_ids
    )
    if words:
        return random.choice(words)

    return db.get_random_word_object(lesson_id=lesson_id, exclude_ids=exclude_ids)


def _sample_unique(primary: List[str], secondary: List[str], count: int) -> List[str]:
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


def _get_smart_wrong_persian_options(word: Word, count: int = 3) -> List[str]:
    same_type_words = (
        db.get_words_by_type(word.word_type, exclude_id=word.id, limit=50)
        if word.word_type
        else []
    )
    other_words = db.get_words_by_type(None, exclude_id=word.id, limit=50)

    same_type = [
        w.persian for w in same_type_words if w.persian and w.persian != word.persian
    ]
    other = [
        w.persian
        for w in other_words
        if w.persian
        and w.persian != word.persian
        and (not word.word_type or w.word_type != word.word_type)
    ]

    return _sample_unique(same_type, other, count)


def _get_smart_wrong_german_options(word: Word, count: int = 3) -> List[str]:
    same_type_words = (
        db.get_words_by_type(word.word_type, exclude_id=word.id, limit=50)
        if word.word_type
        else []
    )
    other_words = db.get_words_by_type(None, exclude_id=word.id, limit=50)

    same_type = [
        w.german for w in same_type_words if w.german and w.german != word.german
    ]
    other = [
        w.german
        for w in other_words
        if w.german
        and w.german != word.german
        and (not word.word_type or w.word_type != word.word_type)
    ]

    return _sample_unique(same_type, other, count)


def _get_smart_wrong_display_german_options(word: Word, count: int = 3) -> List[str]:
    same_type_words = (
        db.get_words_by_type(word.word_type, exclude_id=word.id, limit=50)
        if word.word_type
        else []
    )
    other_words = db.get_words_by_type(None, exclude_id=word.id, limit=50)

    same_type = [
        w.display_german
        for w in same_type_words
        if w.display_german and w.display_german != word.display_german
    ]
    other = [
        w.display_german
        for w in other_words
        if w.display_german
        and w.display_german != word.display_german
        and (not word.word_type or w.word_type != word.word_type)
    ]
    return _sample_unique(same_type, other, count)


async def _gen_article(word: Word, user_id: int, level: str) -> Optional[Dict]:
    if not word.article:
        return None
    return quiz_service.create_article_quiz(word.article, word.german, word.persian)


async def _gen_meaning(word: Word, user_id: int, level: str) -> Optional[Dict]:
    if llm.is_available():
        quiz = await llm.generate_quiz_question(
            word.display_german,
            word.persian,
            level=level,
            user_id=user_id,
            word_id=word.id,
        )
        if quiz:
            return quiz

    wrong = _get_smart_wrong_persian_options(word, count=3)
    return quiz_service.create_meaning_quiz(word.display_german, word.persian, wrong)


async def _gen_reverse(word: Word, user_id: int, level: str) -> Optional[Dict]:
    correct_german = (
        word.display_german
        if (word.word_type == "Noun" and word.article)
        else word.german
    )

    if llm.is_available():
        quiz = await llm.generate_reverse_quiz(
            correct_german,
            word.persian,
            level=level,
            user_id=user_id,
            word_id=word.id,
        )
        if quiz:
            return quiz

    wrong = _get_smart_wrong_display_german_options(word, count=3)
    return quiz_service.create_reverse_quiz(word.persian, correct_german, wrong)


async def _gen_cloze(word: Word, user_id: int, level: str) -> Optional[Dict]:
    ex_de = word.example_de

    if not ex_de and llm.is_available():
        ex_de = await llm.generate_example_sentence(word.display_german, level)

    if not ex_de:
        return None

    wrong = []
    if llm.is_available():
        wrong = await llm.generate_cloze_options(
            word.german,
            ex_de,
            count=3,
            user_id=user_id,
            word_id=word.id,
        )

    if len(wrong) < 3:
        wrong += _get_smart_wrong_german_options(word, count=3 - len(wrong))

    return quiz_service.create_cloze_with_options(
        word.german, word.persian, ex_de, wrong
    )


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
}


def _safe_truncate_html(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text

    plain = re.sub(r"<[^>]+>", "", str(text or ""))
    plain = plain.strip()
    if len(plain) > max_len - 10:
        plain = plain[: max_len - 10] + "\n..."
    return esc(plain)


async def _start_generic_quiz(
    query,
    context,
    word_fetcher: Callable,
    quiz_generator: Callable,
    quiz_type: str,
    source_filter: str = None,
):
    try:
        user_id = query.from_user.id
        lesson_id = context.user_data.get("quiz_lesson_id")

        settings = db.get_user_settings(user_id)
        level = settings.get("preferred_level", "A1")

        session = context.user_data.get("quiz_session")
        exclude_ids = set(session.get("asked_word_ids", [])) if session else set()

        word = None
        quiz = None

        for _ in range(10):
            word = await word_fetcher(user_id, lesson_id, source_filter, exclude_ids)
            if not word:
                break

            if session:
                session.setdefault("asked_word_ids", []).append(word.id)

            try:
                quiz = await quiz_generator(word, user_id, level)
            except Exception as e:
                logger.error("خطا در quiz_generator: %s", e, exc_info=True)
                quiz = None

            if quiz:
                break

            exclude_ids.add(word.id)

        if not word or not quiz:
            if session and session.get("current", 0) > 0:
                await _show_quiz_summary(
                    query, context, header="⚠️ کلمه‌ی مناسب دیگری پیدا نشد."
                )
            else:
                await render(
                    query,
                    "📭 کلمه‌ای برای این کوییز پیدا نشد.",
                    reply_markup=back_inline_keyboard(),
                )
            return

        context.user_data["current_quiz"] = {
            **quiz,
            "type": quiz_type,
            "word": word.german,
            "word_id": word.id,
            "persian": word.persian,
        }

        flash = context.user_data.pop("quiz_flash", None)
        progress = _get_session_progress(context)

        parts = []
        if flash:
            parts.append(esc(flash))
        if progress:
            parts.append(esc(progress))
        parts.append(quiz.get("question", ""))

        msg = "\n".join(parts)

        await render(
            query, msg, reply_markup=quiz_answer_keyboard(quiz.get("options", []))
        )

    except Exception as e:
        logger.error("خطای غیرمنتظره در _start_generic_quiz: %s", e, exc_info=True)
        await render(
            query,
            "❌ خطای غیرمنتظره در شروع کوییز.",
            reply_markup=back_inline_keyboard(),
        )


async def start_quiz_by_type(
    query,
    context,
    quiz_type: str,
    source_filter: str = None,
    fixed_word_ids: Optional[List[int]] = None,
):
    if quiz_type not in QUIZ_REGISTRY:
        quiz_type = "meaning"

    quiz_config = QUIZ_REGISTRY[quiz_type]
    word_fetcher = quiz_config.word_fetcher

    if fixed_word_ids:
        fixed_word_ids = list(dict.fromkeys(fixed_word_ids))

        async def fixed_fetcher(user_id, lesson_id, source_filter, exclude_ids):
            exclude = set(exclude_ids or [])
            for wid in fixed_word_ids:
                if wid not in exclude:
                    w = db.get_word_by_id(wid)
                    if w:
                        return w
            return None

        word_fetcher = fixed_fetcher

    await _start_generic_quiz(
        query,
        context,
        word_fetcher,
        quiz_config.quiz_generator,
        quiz_type,
        source_filter,
    )


def _init_quiz_session(context, total_questions: int):
    context.user_data["quiz_session"] = {
        "current": 0,
        "total": total_questions,
        "correct": 0,
        "wrong": 0,
        "results": [],
        "asked_word_ids": [],
    }


def _update_quiz_session(
    context,
    is_correct: bool,
    word: str,
    word_id: Optional[int],
    user_answer: str,
    correct_answer: str,
):
    session = context.user_data.get("quiz_session")
    if not session:
        return

    session["current"] += 1
    session["correct" if is_correct else "wrong"] += 1
    session["results"].append(
        {
            "word": word,
            "word_id": word_id,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
        }
    )


def _get_session_progress(context) -> str:
    from ui import progress_bar

    session = context.user_data.get("quiz_session")
    if not session:
        return ""
    cur = session["current"] + 1
    tot = session["total"] or 1
    bar = progress_bar(cur, tot)
    return (
        f"[{bar}] سوال {cur} از {tot} | "
        f"✅ {session['correct']} | ❌ {session['wrong']}"
    )


def _is_session_finished(context) -> bool:
    session = context.user_data.get("quiz_session")
    if not session:
        return True
    return session["current"] >= session["total"]


async def _show_quiz_summary(query, context, header: str = ""):
    session = context.user_data.pop("quiz_session", None)
    context.user_data.pop("current_quiz", None)
    context.user_data.pop("quiz_fixed_word_ids", None)

    if not session:
        await render(query, "🏁 کوییز تمام شد.", reply_markup=back_inline_keyboard())
        return

    wrong_ids = list(
        dict.fromkeys(
            [
                r["word_id"]
                for r in session["results"]
                if not r["is_correct"] and r.get("word_id")
            ]
        )
    )

    if wrong_ids:
        context.user_data["quiz_wrong_word_ids"] = wrong_ids
    else:
        context.user_data.pop("quiz_wrong_word_ids", None)

    accuracy = (
        (session["correct"] / session["total"] * 100) if session["total"] > 0 else 0
    )

    lines = []
    if header:
        lines.append(header)

    lines.append("<b>🏁 کوییز تمام شد!</b>")
    lines.append(f"✅ درست: {session['correct']}")
    lines.append(f"❌ اشتباه: {session['wrong']}")
    lines.append(f"🎯 دقت: {accuracy:.1f}%")

    details_limit = 20
    if session["results"]:
        lines.append("\n<b>جزئیات:</b>")
        for i, r in enumerate(session["results"][:details_limit], 1):
            emoji = "✅" if r["is_correct"] else "❌"
            line = f"{i}. {emoji} <b>{esc(r['word'])}</b>"
            if not r["is_correct"]:
                line += f"\n   شما: {esc(r['user_answer'])}"
                line += f"\n   درست: {esc(r['correct_answer'])}"
            lines.append(line)

        if len(session["results"]) > details_limit:
            lines.append(f"\n... و {len(session['results']) - details_limit} مورد دیگر")

    text = "\n".join(lines)

    if len(text) > 4000:
        text = _safe_truncate_html(text, 4000)

    keyboard = []
    if wrong_ids:
        keyboard.append(
            [InlineKeyboardButton("🔁 فقط اشتباه‌ها", callback_data="quiz_retry_wrong")]
        )

    keyboard.append(
        [InlineKeyboardButton("🔄 کوییز جدید", callback_data="show_quiz_menu")]
    )
    keyboard.append(
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")]
    )

    await render(query, text, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_quiz_answer(query, context):
    if "current_quiz" not in context.user_data:
        try:
            await query.answer("⚠️ کوییز فعال نیست.", show_alert=True)
        except Exception:
            pass
        return

    quiz_info = context.user_data["current_quiz"]

    try:
        chosen_index = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await query.answer("⚠️ گزینه نامعتبر.", show_alert=True)
        return

    options = quiz_info.get("options", [])
    if chosen_index < 0 or chosen_index >= len(options):
        await query.answer("⚠️ گزینه نامعتبر.", show_alert=True)
        return

    user_id = query.from_user.id
    is_correct = chosen_index == quiz_info["correct_index"]
    user_answer_text = options[chosen_index]
    correct_answer = (
        quiz_info.get("correct_answer") or options[quiz_info["correct_index"]]
    )

    db.update_quiz_stats(user_id, is_correct)

    if quiz_info.get("word_id"):
        grade = fsrs.grade_from_correctness(is_correct)
        fsrs.review(user_id, quiz_info["word_id"], grade)

    db.record_activity(user_id, 10 if is_correct else 0)

    _update_quiz_session(
        context,
        is_correct,
        quiz_info.get("word", ""),
        quiz_info.get("word_id"),
        user_answer_text,
        correct_answer,
    )

    context.user_data.pop("current_quiz", None)

    if is_correct:
        try:
            await query.answer("✅ درست بود!", show_alert=False)
        except Exception:
            pass

        if config.QUIZ_AUTO_NEXT_ON_CORRECT:
            if _is_session_finished(context):
                await _show_quiz_summary(query, context)
            else:
                context.user_data["quiz_flash"] = "✅ درست بود!"
                await _send_next_quiz(query, context)
            return

        feedback = "✅ آفرین! جواب درست بود! 🎉"
    else:
        try:
            await query.answer("❌ اشتباه بود", show_alert=False)
        except Exception:
            pass

        feedback = f"❌ اشتباه بود!\n✅ جواب درست: {esc(correct_answer)}"

        if llm.is_available():
            explanation = await llm.explain_mistake(
                quiz_info.get("word", ""),
                user_answer_text,
                correct_answer,
                quiz_info.get("type", "meaning"),
            )
            if explanation:
                feedback += f"\n💡 {esc(explanation)}"

    if _is_session_finished(context):
        await _show_quiz_summary(query, context, header=feedback)
    else:
        progress = _get_session_progress(context)
        text = feedback
        if progress:
            text += f"\n{esc(progress)}"

        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⏭️ سوال بعدی", callback_data="quiz_next")],
                [
                    InlineKeyboardButton(
                        "🔙 منوی اصلی", callback_data="back_to_main_menu"
                    )
                ],
            ]
        )

        await render(query, text, reply_markup=kb)


async def start_quiz_session(
    query,
    context,
    quiz_type: str = "meaning",
    count: int = 10,
    source_filter: str = None,
):
    if quiz_type not in QUIZ_REGISTRY:
        quiz_type = "meaning"

    _init_quiz_session(context, count)
    context.user_data["quiz_type"] = quiz_type
    context.user_data["quiz_source_filter"] = source_filter
    context.user_data.pop("quiz_fixed_word_ids", None)

    await _send_next_quiz(query, context)


async def start_wrong_quiz(query, context):
    wrong_ids = list(dict.fromkeys(context.user_data.get("quiz_wrong_word_ids", [])))

    if not wrong_ids:
        await render(
            query, "📭 لیست اشتباه‌ها موجود نیست.", reply_markup=back_inline_keyboard()
        )
        return

    words = db.get_word_objects_by_ids(wrong_ids)
    if not words:
        await render(
            query,
            "📭 کلمه‌ای برای مرور اشتباه‌ها پیدا نشد.",
            reply_markup=back_inline_keyboard(),
        )
        return

    random.shuffle(words)

    _init_quiz_session(context, len(words))
    context.user_data["quiz_fixed_word_ids"] = [w.id for w in words]
    context.user_data["quiz_type"] = context.user_data.get("quiz_type", "meaning")
    context.user_data["quiz_source_filter"] = None
    context.user_data.pop("quiz_lesson_id", None)

    await _send_next_quiz(query, context)


async def start_quiz_session_with_words(query, context, word_ids):
    word_ids = list(dict.fromkeys(word_ids or []))
    words = db.get_word_objects_by_ids(word_ids)

    if not words:
        await render(query, "📭 کلمه‌ای پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    random.shuffle(words)

    _init_quiz_session(context, len(words))
    context.user_data["quiz_fixed_word_ids"] = [w.id for w in words]
    context.user_data["quiz_type"] = "meaning"
    context.user_data["quiz_source_filter"] = None
    context.user_data.pop("quiz_lesson_id", None)

    await _send_next_quiz(query, context)


async def _send_next_quiz(query, context):
    if "quiz_session" not in context.user_data:
        await render(
            query, "⚠️ کوییزی فعال نیست. /menu", reply_markup=back_inline_keyboard()
        )
        return

    quiz_type = context.user_data.get("quiz_type", "meaning")
    source_filter = context.user_data.get("quiz_source_filter")
    fixed_word_ids = context.user_data.get("quiz_fixed_word_ids")

    await start_quiz_by_type(query, context, quiz_type, source_filter, fixed_word_ids)
