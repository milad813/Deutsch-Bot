"""Story quiz functionality."""

import json
import logging
import random
from typing import List, Dict, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services import db
from ui import _short_label, back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)


def _safe_json_list(raw):
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def start_story_quiz(query, context, story_id: int):
    """Start a quiz based on story comprehension questions."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    questions = _safe_json_list(story.get("questions_json"))
    questions = [q for q in questions if isinstance(q, dict) and q.get("question")]

    if not questions:
        await render(
            query, "📭 سوالی برای این داستان ثبت نشده.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📖 بازگشت", callback_data=f"story_view:{story_id}")],
            ]),
        )
        return

    comp_qs = [q for q in questions if q.get("question_type") == "comprehension"]
    vocab_qs = [q for q in questions if q.get("question_type") == "vocabulary"]
    detail_qs = [q for q in questions if q.get("question_type") == "detail"]

    if not comp_qs and not vocab_qs and not detail_qs:
        comp_qs = questions

    ordered = comp_qs + detail_qs + vocab_qs

    context.user_data["story_quiz"] = {
        "story_id": story_id,
        "questions": ordered,
        "current": 0,
        "correct": 0,
        "wrong": 0,
        "comprehension_correct": 0, "comprehension_wrong": 0,
        "vocabulary_correct": 0, "vocabulary_wrong": 0,
        "detail_correct": 0, "detail_wrong": 0,
    }

    await _show_story_question(query, context)


async def _show_story_question(query, context):
    """Display a quiz question."""
    quiz = context.user_data.get("story_quiz")
    if not quiz:
        await render(query, "⚠️ کوییز فعال نیست.", reply_markup=back_inline_keyboard())
        return

    q = quiz["questions"][quiz["current"]]
    options = list(q.get("options") or [])
    correct = str(q.get("correct_answer") or "").strip()

    if correct and correct not in options:
        options.append(correct)

    if len(options) > 4:
        wrongs = [o for o in options if o != correct]
        random.shuffle(wrongs)
        options = [correct] + wrongs[:3]

    random.shuffle(options)
    quiz["current_options"] = options
    quiz["current_correct_index"] = options.index(correct) if correct in options else 0

    num = quiz["current"] + 1
    total = len(quiz["questions"])

    q_type = q.get("question_type", "comprehension")
    labels = {
        "comprehension": "📖 درک مطلب",
        "vocabulary": "🧠 واژگان",
        "detail": "🔍 جزئیات",
    }
    type_label = labels.get(q_type, "📖 درک مطلب")

    msg = f"❓ <b>سوال {num} از {total}</b> [{type_label}]\n{esc(q['question'])}"

    kb = []
    for i, opt in enumerate(options):
        label = f"{chr(65 + i)}) {opt}"
        kb.append([InlineKeyboardButton(_short_label(label, 64), callback_data=f"story_ans:{i}")])

    kb.append([InlineKeyboardButton("🔙 خروج", callback_data=f"story_view:{quiz['story_id']}")])

    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb))


async def handle_story_answer(query, context, suffix: str):
    """Handle user's answer to a story quiz question."""
    quiz = context.user_data.get("story_quiz")
    if not quiz:
        await render(query, "⚠️ کوییز فعال نیست.", reply_markup=back_inline_keyboard())
        return

    try:
        selected_idx = int(suffix)
    except ValueError:
        await render(query, "⚠️ گزینه نامعتبر.", reply_markup=back_inline_keyboard())
        return

    q = quiz["questions"][quiz["current"]]
    correct = str(q.get("correct_answer") or "")
    options = quiz.get("current_options", [])

    if not options or selected_idx >= len(options):
        await render(query, "⚠️ گزینه نامعتبر.", reply_markup=back_inline_keyboard())
        return

    selected = options[selected_idx]
    is_correct = (selected == correct)

    # Update stats
    q_type = q.get("question_type", "comprehension")
    if is_correct:
        quiz["correct"] += 1
        if q_type == "comprehension":
            quiz["comprehension_correct"] += 1
        elif q_type == "vocabulary":
            quiz["vocabulary_correct"] += 1
        elif q_type == "detail":
            quiz["detail_correct"] += 1
    else:
        quiz["wrong"] += 1
        if q_type == "comprehension":
            quiz["comprehension_wrong"] += 1
        elif q_type == "vocabulary":
            quiz["vocabulary_wrong"] += 1
        elif q_type == "detail":
            quiz["detail_wrong"] += 1

    # Show feedback
    if is_correct:
        fb_msg = f"✅ آفرین! پاسخ درست بود.\n\n📊 امتیاز: {quiz['correct']} از {quiz['current'] + 1}"
    else:
        fb_msg = (
            f"❌ نادرست. پاسخ صحیح:\n<b>{esc(correct)}</b>\n\n"
            f"📊 امتیاز: {quiz['correct']} از {quiz['current'] + 1}"
        )

    # Next question or summary
    if quiz["current"] < len(quiz["questions"]) - 1:
        quiz["current"] += 1
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ سوال بعدی", callback_data=f"story_ans:next")],
            [InlineKeyboardButton("🔙 خروج", callback_data=f"story_view:{quiz['story_id']}")],
        ])
        await render(query, fb_msg, reply_markup=kb)
        
        # Auto-advance after delay (optional)
        # For now, wait for user to click next
    else:
        await _show_story_quiz_summary(query, context)


async def _show_story_quiz_summary(query, context):
    """Show quiz summary with detailed statistics."""
    quiz = context.user_data.get("story_quiz")
    if not quiz:
        await render(query, "⚠️ کوییز فعال نیست.", reply_markup=back_inline_keyboard())
        return

    total = quiz["correct"] + quiz["wrong"]
    accuracy = (quiz["correct"] / total * 100) if total > 0 else 0

    msg = f"🏁 <b>پایان کوییز داستان</b>\n\n"
    msg += f"📊 کل سوالات: {total}\n"
    msg += f"✅ درست: {quiz['correct']}\n"
    msg += f"❌ نادرست: {quiz['wrong']}\n"
    msg += f"🎯 دقت: {accuracy:.1f}%\n\n"

    # Breakdown by type
    comp_total = quiz["comprehension_correct"] + quiz["comprehension_wrong"]
    vocab_total = quiz["vocabulary_correct"] + quiz["vocabulary_wrong"]
    detail_total = quiz["detail_correct"] + quiz["detail_wrong"]

    if comp_total > 0:
        comp_acc = quiz["comprehension_correct"] / comp_total * 100
        msg += f"📖 درک مطلب: {quiz['comprehension_correct']}/{comp_total} ({comp_acc:.0f}%)\n"
    if vocab_total > 0:
        vocab_acc = quiz["vocabulary_correct"] / vocab_total * 100
        msg += f"🧠 واژگان: {quiz['vocabulary_correct']}/{vocab_total} ({vocab_acc:.0f}%)\n"
    if detail_total > 0:
        detail_acc = quiz["detail_correct"] / detail_total * 100
        msg += f"🔍 جزئیات: {quiz['detail_correct']}/{detail_total} ({detail_acc:.0f}%)\n"

    # Recommendations
    if accuracy >= 80:
        msg += "\n🎉 عالی! تسلط خوبی روی داستان داری."
    elif accuracy >= 60:
        msg += "\n👍 خوبه، اما می‌تونی بهتر هم بشی."
    else:
        msg += "\n💡 پیشنهاد: داستان را دوباره بخوان و مرور کن."

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{quiz['story_id']}")],
        [InlineKeyboardButton("🔁 تکرار کوییز", callback_data=f"story_quiz:{quiz['story_id']}")],
        [InlineKeyboardButton("🔙 بازگشت به درس", callback_data=f"lesson_{db.get_story(quiz['story_id'])['lesson_id']}")],
    ])

    await render(query, msg, reply_markup=kb)
