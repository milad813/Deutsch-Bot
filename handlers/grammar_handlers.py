import json
import logging
import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services import db
from ui import _short_label, back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)


def _grammar_quiz_keyboard(options, point_id):
    kb = []
    for i, opt in enumerate(options):
        label = f"{chr(65 + i)}) {opt}"
        kb.append(
            [
                InlineKeyboardButton(
                    _short_label(label, 64), callback_data=f"grammar_ans:{i}"
                )
            ]
        )
    kb.append(
        [
            InlineKeyboardButton(
                "🔙 بازگشت به نکته", callback_data=f"grammar_point:{point_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(kb)


async def show_grammar_menu(query, context, lesson_id: int):
    points = db.get_grammar_points_by_lesson(lesson_id)
    if not points:
        await render(
            query,
            "📐 هنوز گرامری برای این درس ثبت نشده.",
            reply_markup=back_inline_keyboard("🔙 بازگشت", f"lesson_{lesson_id}"),
        )
        return
    kb = []
    for p in points:
        title = p.get("title_fa") or p.get("topic_key") or "نکته"
        kb.append(
            [
                InlineKeyboardButton(
                    _short_label(f"📘 {title}"),
                    callback_data=f"grammar_point:{p['id']}",
                )
            ]
        )
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"lesson_{lesson_id}")])
    await render(
        query,
        "📐 <b>گرامر این درس</b>\nیک نکته را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def show_grammar_point(query, context, point_id: int):
    p = db.get_grammar_point(point_id)
    if not p:
        await render(query, "❌ نکته پیدا نشد.", reply_markup=back_inline_keyboard())
        return
    try:
        examples = json.loads(p.get("examples_json") or "[]")
    except Exception:
        examples = []
        examples = [ex for ex in examples if isinstance(ex, dict)]
    msg = f"📘 <b>{esc(p['title_fa'])}</b>\n\n💡 {esc(p['explanation_fa'])}\n"
    if p.get("rule_de"):
        msg += f"\n🇩🇪 <code>{esc(p['rule_de'])}</code>\n"
    if examples:
        msg += "\n<b>مثال:</b>\n"
        for ex in examples[:3]:
            msg += f"🇩 {esc(ex.get('de', ''))}\n🇮🇷 <i>{esc(ex.get('fa', ''))}</i>\n"
    kb = [
        [
            InlineKeyboardButton(
                "✍️ تمرین این نکته", callback_data=f"grammar_quiz:{p['id']}"
            )
        ]
    ]
    kb.append(
        [
            InlineKeyboardButton(
                "🔙 بازگشت", callback_data=f"grammar_lesson:{p['lesson_id']}"
            )
        ]
    )
    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb))


async def start_grammar_quiz(query, context, point_id: int):
    p = db.get_grammar_point(point_id)
    if not p:
        await render(query, "❌ نکته پیدا نشد.", reply_markup=back_inline_keyboard())
        return
    try:
        exercises = json.loads(p.get("exercises_json") or "[]")
    except Exception:
        exercises = []
        exercises = [ex for ex in exercises if isinstance(ex, dict)]
    if not exercises:
        await render(
            query,
            "📭 تمرینی برای این نکته ثبت نشده.",
            reply_markup=back_inline_keyboard("🔙 بازگشت", f"grammar_point:{p['id']}"),
        )
        return
    ex = random.choice(exercises)
    correct = str(ex.get("correct") or "").strip()
    if not correct:
        await render(
            query,
            "📭 این تمرین معتبر نیست.",
            reply_markup=back_inline_keyboard("🔙 بازگشت", f"grammar_point:{p['id']}"),
        )
        return

    distractors = [
        str(d).strip() for d in (ex.get("distractors") or []) if str(d).strip()
    ]
    distractors = [d for d in distractors if d != correct]
    distractors = list(dict.fromkeys(distractors))
    random.shuffle(distractors)

    options = [correct] + distractors[:3]
    random.shuffle(options)
    context.user_data["grammar_current"] = {
        "correct": correct,
        "correct_index": options.index(correct),
        "options": options,
        "sentence": ex.get("sentence_de", ""),
        "explanation": ex.get("explanation_fa", ""),
        "point_id": p["id"],
        "lesson_id": p["lesson_id"],
    }
    msg = f"✍️ <b>تمرین گرامر</b>\n🇩 {esc(ex.get('sentence_de', ''))}"
    await render(query, msg, reply_markup=_grammar_quiz_keyboard(options, p["id"]))


async def handle_grammar_answer(query, context, suffix: str):
    cur = context.user_data.get("grammar_current")
    if not cur:
        try:
            await query.answer("⚠️ تمرینی فعال نیست.", show_alert=True)
        except Exception:
            pass
        return
    try:
        chosen = int(suffix)
    except ValueError:
        return
    options = cur["options"]
    if chosen < 0 or chosen >= len(options):
        return
    is_correct = chosen == cur["correct_index"]
    if is_correct:
        try:
            await query.answer("✅ درست!", show_alert=False)
        except Exception:
            pass
        msg = "✅ <b>آفرین! درست بود.</b>"
    else:
        try:
            await query.answer(f"❌ جواب: {cur['correct']}", show_alert=True)
        except Exception:
            pass
        msg = f"❌ اشتباه بود.\n✅ جواب درست: <b>{esc(cur['correct'])}</b>"
    if cur.get("explanation"):
        msg += f"\n💡 {esc(cur['explanation'])}"
    kb = [
        [
            InlineKeyboardButton(
                "✍️ تمرین دیگر", callback_data=f"grammar_quiz:{cur['point_id']}"
            )
        ]
    ]
    kb.append(
        [
            InlineKeyboardButton(
                "🔙 بازگشت به نکته", callback_data=f"grammar_point:{cur['point_id']}"
            )
        ]
    )
    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb))
