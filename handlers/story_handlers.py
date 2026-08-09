import json
import logging
import random
import re
from typing import List, Dict, Optional, Set
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from services import db, llm, tts
from ui import _short_label, back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)

# ─── تنظیمات داستان هوشمند ───────────────────────────────────────
STORY_WORD_TYPES = ("Noun", "Verb", "Adjective")
MAX_STORY_WORDS = 12
MIN_STORY_WORDS = 5

# ─── ژانرها ───────────────────────────────────────────────────────
GENRES = [
    {"id": "daily", "de": "Alltag", "fa": "روزمره", "desc": "موقعیت‌های عادی زندگی"},
    {"id": "adventure", "de": "Abenteuer", "fa": "ماجراجویی", "desc": "سفر یا اتفاق هیجان‌انگیز"},
    {"id": "mystery", "de": "Rätsel", "fa": "معمایی", "desc": "حل یک مشکل یا معما"},
    {"id": "humor", "de": "Humor", "fa": "طنز", "desc": "اتفاق خنده‌دار یا غیرمنتظره"},
    {"id": "social", "de": "Sozial", "fa": "اجتماعی", "desc": "دیدار با دوستان یا خانواده"},
]

# ─── ژانر مجاز بر اساس سطح ───────────────────────────────────────
GENRE_BY_LEVEL = {
    "A1": ["daily", "social"],
    "A2": ["daily", "social", "humor"],
    "B1": ["daily", "social", "humor", "adventure"],
    "B2": [g["id"] for g in GENRES],
}


# ─── نسبت کلمات بر اساس سطح ──────────────────────────────────────
def _get_word_ratios(level: str) -> tuple:
    """نسبت (new, review, mastered) بر اساس سطح."""
    if level == "A1":
        return 0.3, 0.5, 0.2
    elif level == "A2":
        return 0.4, 0.4, 0.2
    else:  # B1, B2
        return 0.5, 0.3, 0.2


# ─── تنظیمات تکرار کلمات ─────────────────────────────────────────
def _get_repetition_rule(word_status: str) -> str:
    """قانون تکرار بر اساس وضعیت کلمه."""
    if word_status == "weak":
        return "2-3 times"
    elif word_status == "new":
        return "1-2 times"
    else:  # mastered
        return "exactly once"


def _safe_json_list(raw):
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _safe_id_list(raw):
    result = []
    for item in _safe_json_list(raw):
        try:
            result.append(int(item))
        except Exception:
            continue
    return result


# ─── انتخاب هوشمند کلمات ─────────────────────────────────────────
def _select_smart_words(
    user_id: int, lesson_id: int, exclude_ids: Set[int], level: str = "A1"
) -> List[Dict]:
    """انتخاب هوشمند کلمات بر اساس وضعیت SRS و درس."""
    all_words = db.get_words_by_lesson_full(lesson_id)
    if not all_words:
        return []

    story_friendly = [w for w in all_words if w.get("word_type") in STORY_WORD_TYPES]

    new_words = []
    weak_words = []
    mastered_words = []

    for w in story_friendly:
        wid = w["id"]
        if wid in exclude_ids:
            continue
        stats = db.get_word_stats_full(user_id, wid)
        if not stats:
            new_words.append(w)
        elif stats.get("phase") == "learning" or (
            stats.get("wrong", 0) > stats.get("correct", 0)
        ):
            weak_words.append(w)
        else:
            mastered_words.append(w)

    # ─── نسبت بر اساس سطح ───
    new_ratio, review_ratio, mastered_ratio = _get_word_ratios(level)
    total_needed = min(MAX_STORY_WORDS, len(story_friendly))
    n_new = max(1, int(total_needed * new_ratio))
    n_weak = max(1, int(total_needed * review_ratio))
    n_mastered = max(0, total_needed - n_new - n_weak)

    selected = []

    # 1. کلمات جدید
    random.shuffle(new_words)
    selected.extend(new_words[:n_new])

    # 2. کلمات ضعیف (از درس فعلی)
    random.shuffle(weak_words)
    selected.extend(weak_words[:n_weak])

    # 3. اگر کلمات ضعیف کم بود، از ضعیف‌های بین‌درسی
    if len(selected) < n_new + n_weak:
        remaining_weak = (n_new + n_weak) - len(selected)
        if remaining_weak > 0:
            try:
                exclude_list = list(exclude_ids)[:500]
                global_weak_words = db.words.get_weak(
                    user_id=user_id,
                    limit=remaining_weak * 2,
                    exclude_ids=exclude_list,
                )
                for w in global_weak_words:
                    wd = {
                        "id": w.id,
                        "german": w.german,
                        "persian": w.persian,
                        "article": w.article,
                        "word_type": w.word_type,
                    }
                    if not any(x["id"] == w.id for x in selected):
                        selected.append(wd)
                    if len(selected) >= n_new + n_weak:
                        break
            except Exception as e:
                logger.warning("خطا در گرفتن کلمات ضعیف بین‌درسی: %s", e)

    # 4. کلمات تثبیت‌شده
    if len(selected) < total_needed:
        remaining = total_needed - len(selected)
        random.shuffle(mastered_words)
        selected.extend(mastered_words[:remaining])

    # 5. پر کردن با بقیه کلمات درس
    if len(selected) < MIN_STORY_WORDS:
        used_ids = {w["id"] for w in selected}
        for w in story_friendly:
            if w["id"] not in used_ids and w["id"] not in exclude_ids:
                selected.append(w)
            if len(selected) >= MIN_STORY_WORDS:
                break

    return selected[:MAX_STORY_WORDS]


# ─── انتخاب ژانر هوشمند ──────────────────────────────────────────
def _select_genre(level: str, lesson_title: str) -> Dict:
    """انتخاب ژانر بر اساس سطح و موضوع درس."""
    allowed_ids = GENRE_BY_LEVEL.get(level, ["daily"])
    allowed_genres = [g for g in GENRES if g["id"] in allowed_ids]

    # اگر موضوع درس مشخص است، ژانر مرتبط انتخاب کن
    lesson_lower = (lesson_title or "").lower()
    topic_genre_map = {
        "einkaufen": ["daily"],
        "familie": ["daily", "social"],
        "reisen": ["adventure", "daily"],
        "essen": ["daily"],
        "arbeit": ["daily", "social"],
        "wohnen": ["daily"],
        "freizeit": ["daily", "humor"],
        "arzt": ["daily"],
        "schule": ["daily"],
        "wetter": ["daily"],
    }
    for topic, genre_ids in topic_genre_map.items():
        if topic in lesson_lower:
            matched = [g for g in GENRES if g["id"] in genre_ids and g["id"] in allowed_ids]
            if matched:
                return random.choice(matched)

    return random.choice(allowed_genres) if allowed_genres else GENRES[0]


# ─── تشخیص سطح تطبیقی ────────────────────────────────────────────
def _get_adaptive_level(user_id: int, lesson_level: str) -> str:
    """تنظیم سطح داستان بر اساس عملکرد کاربر."""
    try:
        weekly = db.learning.get_weekly_stats(user_id)
        accuracy = weekly.get("accuracy", 0)
        total = weekly.get("total_answers", 0)

        # اگر داده کافی نیست، سطح درس را برگردان
        if total < 10:
            return lesson_level

        levels = ["A1", "A2", "B1", "B2"]
        try:
            idx = levels.index(lesson_level)
        except ValueError:
            return lesson_level

        if accuracy < 55 and idx > 0:
            return levels[idx - 1]  # یک پله پایین‌تر
        elif accuracy > 85 and idx < len(levels) - 1:
            return levels[idx + 1]  # یک پله بالاتر

        return lesson_level
    except Exception:
        return lesson_level


# ─── ساخت پرامپت داستان ──────────────────────────────────────────
def _build_enhanced_prompt(
    words: List[Dict],
    level: str,
    lesson_title: str,
    genre: Dict,
    story_number: int = 1,
    total_stories_in_series: int = 1,
) -> str:
    """ساخت پرامپت پیشرفته با ساختار داستانی واقعی."""
    word_lines = []
    for w in words:
        art = (w.get("article") or "").strip()
        disp = f"{art} {w['german']}".strip() if art else w["german"]
        # تشخیص وضعیت کلمه برای قانون تکرار
        stats = None
        try:
            stats = db.get_word_stats_full(1, w["id"])  # user_id=1 (admin)
        except Exception:
            pass

        if not stats:
            status = "new"
        elif stats.get("phase") == "learning" or (
            stats.get("wrong", 0) > stats.get("correct", 0)
        ):
            status = "weak"
        else:
            status = "mastered"

        rep_rule = _get_repetition_rule(status)
        word_lines.append(
            f'- id={w["id"]} | "{disp}" = {w["persian"]} | status={status} | repeat={rep_rule}'
        )

    word_list = "\n".join(word_lines)

    grammar_rules = {
        "A1": "Only Präsens. Very short sentences (max 8 words). No Nebensätze. No Perfekt.",
        "A2": "Präsens + Perfekt. Simple Nebensätze with 'weil', 'dass'. Max 12 words/sentence.",
        "B1": "Präteritum allowed. Konjunktiv II for politeness. Compound sentences OK.",
        "B2": "All tenses. Complex sentence structures allowed.",
    }
    grammar_hint = grammar_rules.get(level, grammar_rules["A1"])

    # ─── Narrow Reading: اگر بخشی از سری است ───
    series_instruction = ""
    if total_stories_in_series > 1:
        series_instruction = f"""
NARROW READING SERIES: This is story {story_number} of {total_stories_in_series} about "{lesson_title}".
- Use a DIFFERENT situation but the SAME theme.
- Introduce 1-2 NEW vocabulary items that were NOT in previous stories.
- Reuse the theme's core vocabulary in a new context.
"""

    return f"""You are an expert German language teacher and creative storyteller.
Write a SHORT STORY for {level} learners.

LESSON THEME: {lesson_title or "General"}
GENRE: {genre['de']} ({genre['fa']}) - {genre['desc']}
LEVEL: {level}
GRAMMAR RULES: {grammar_hint}
{series_instruction}
TARGET WORDS (must ALL appear naturally):
{word_list}

STORY STRUCTURE REQUIREMENTS:
1. CHARACTER: Give the main character a name and one personality trait.
2. SETTING: Clearly establish where and when (1-2 sentences).
3. CONFLICT: Something small goes wrong or a challenge appears.
4. RESOLUTION: The problem is solved using at least ONE target word.
5. ENDING: A satisfying emotional conclusion or short dialogue.
6. DIALOGUE: Include at least 2 lines of direct speech („...").

FORMATTING RULES:
- The story text must be 100% German. Do NOT add any Persian translations inside the story text.
- The text_fa field will contain the full Persian translation separately.
- Story length: 8-12 sentences for A1, 10-15 for A2+.
- Do NOT use idioms beyond {level}.
- Keep sentences natural and varied in structure.

REPETITION RULES:
- Weak words: appear 2-3 times in different contexts.
- New words: appear 1-2 times.
- Mastered words: appear exactly once.
- Do NOT force repetition if it makes the story unnatural.

QUESTIONS: Create 4 questions IN GERMAN:
- 2 COMPREHENSION questions about the plot (set "question_type": "comprehension", "word_id": null)
- 2 VOCABULARY questions about specific target words (set "question_type": "vocabulary", "word_id": <id>)

Example comprehension question:
"Warum geht Anna zum Markt?" (word_id: null, question_type: "comprehension")

Example vocabulary question:
"Was bedeutet „bezahlen" in diesem Text?" (word_id: 42, question_type: "vocabulary")

Return ONLY valid JSON:
{{
    "title_de": "German title",
    "title_fa": "Persian title",
    "text_de": "Story text in 100% German, NO Persian translations inside",
    "text_fa": "Natural Persian translation of the full story",
    "questions": [
        {{
            "question": "German comprehension question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "exact text of correct option",
            "word_id": null,
            "question_type": "comprehension"
        }},
        {{
            "question": "Was bedeutet „Word"?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "exact text of correct option",
            "word_id": 123,
            "question_type": "vocabulary"
        }}
    ]
}}"""


# ─── تولید داستان ─────────────────────────────────────────────────
async def _generate_story_for_lesson(
    user_id: int, lesson_id: int, exclude_ids: Set[int] = None
):
    """تولید داستان پویا با کلمات هوشمند."""
    exclude_ids = exclude_ids or set()

    # ─── سطح تطبیقی ───
    lesson_level = db.get_book_level_by_lesson(lesson_id) or "A1"
    level = _get_adaptive_level(user_id, lesson_level)

    words = _select_smart_words(user_id, lesson_id, exclude_ids, level)
    if len(words) < MIN_STORY_WORDS:
        logger.warning(
            "کلمات کافی برای داستان درس %d یافت نشد (%d کلمه)",
            lesson_id,
            len(words),
        )
        return None

    lesson = db.get_lesson(lesson_id)
    lesson_title = lesson[1] if lesson and len(lesson) > 1 else ""

    # ─── Narrow Reading: تعداد داستان‌های قبلی ───
    story_count = db.get_story_count_by_lesson(lesson_id)
    total_in_series = 3  # هر موضوع ۳ داستان
    story_number = (story_count % total_in_series) + 1

    # ─── ژانر هوشمند ───
    genre = _select_genre(level, lesson_title)

    prompt = _build_enhanced_prompt(
        words, level, lesson_title, genre,
        story_number=story_number,
        total_stories_in_series=total_in_series,
    )

    for attempt in range(3):
        try:
            content = await llm._chat(
                "You are a creative German language teacher. Output ONLY valid JSON.",
                prompt,
                temperature=0.9,
                max_tokens=1500,
            )
            if not content:
                continue

            result = json.loads(llm._clean_json(content))
            if not isinstance(result, dict):
                continue

            text_de = str(result.get("text_de") or "").strip()
            if not text_de:
                continue

            # ─── اعتبارسنجی: بررسی عدم وجود فارسی در متن آلمانی ───
            persian_in_text = bool(re.search(r"[\u0600-\u06FF]", text_de))
            if persian_in_text:
                # حذف پرانتزهای فارسی به عنوان fallback
                text_de = re.sub(r"\s*\([^)]*[\u0600-\u06FF][^)]*\)", "", text_de).strip()

            # ─── اعتبارسنجی استفاده از کلمات ───
            text_lower = text_de.lower()
            used = sum(1 for w in words if w["german"].lower() in text_lower)
            usage_ratio = used / len(words) if words else 0

            if usage_ratio < 0.6:
                logger.warning(
                    "داستان فقط %d/%d کلمه داشت (%.0f%%) - تلاش %d",
                    used,
                    len(words),
                    usage_ratio * 100,
                    attempt + 1,
                )
                continue

            # ─── اعتبارسنجی سوالات ───
            questions = result.get("questions") or []
            target_ids = [w["id"] for w in words]
            target_id_set = set(target_ids)
            valid_q = []

            for q in questions:
                if not isinstance(q, dict) or not q.get("question"):
                    continue
                options = q.get("options") or []
                correct = q.get("correct_answer")
                if len(options) < 2 or not correct:
                    continue

                # ─── question_type ───
                q_type = q.get("question_type", "comprehension")
                if q_type not in ("comprehension", "vocabulary"):
                    q_type = "comprehension"
                q["question_type"] = q_type

                # ─── word_id فقط برای vocabulary ───
                try:
                    word_id = int(q.get("word_id"))
                except Exception:
                    word_id = None

                if q_type == "vocabulary" and word_id not in target_id_set:
                    word_id = None
                elif q_type == "comprehension":
                    word_id = None

                q["word_id"] = word_id
                valid_q.append(q)

            # ─── ذخیره داستان ───
            story_id = db.add_story(
                lesson_id=lesson_id,
                title_de=str(result.get("title_de") or "").strip(),
                title_fa=str(result.get("title_fa") or "").strip(),
                text_de=text_de,
                text_fa=str(result.get("text_fa") or "").strip(),
                target_word_ids=json.dumps(target_ids),
                questions_json=json.dumps(valid_q, ensure_ascii=False),
                level=level,
            )

            logger.info(
                "✅ داستان id=%d برای درس %d ساخته شد (%d کلمه، %d سوال، ژانر: %s، سری: %d/%d)",
                story_id,
                lesson_id,
                len(words),
                len(valid_q),
                genre["fa"],
                story_number,
                total_in_series,
            )
            return db.get_story(story_id)

        except Exception as e:
            logger.warning("خطا در ساخت داستان (تلاش %d): %s", attempt + 1, e)
            continue

    return None


# ─── منوی داستان ──────────────────────────────────────────────────
async def show_story_menu(query, context, lesson_id: int):
    """منوی داستان - همیشه تولید داستان جدید."""
    user_id = query.from_user.id

    if not llm.is_available():
        await render(
            query,
            "❌ قابلیت LLM فعال نیست.\nدر <code>.env</code> کلید <code>GROQ_API_KEY</code> را تنظیم کن.",
            reply_markup=back_inline_keyboard("🔙 بازگشت", f"lesson_{lesson_id}"),
        )
        return

    session_stories = context.user_data.get("story_session_word_ids", [])
    exclude_ids = set(session_stories)

    try:
        await query.answer("📖 در حال ساخت داستان جدید...", show_alert=False)
    except Exception:
        pass

    story = await _generate_story_for_lesson(user_id, lesson_id, exclude_ids)

    if story:
        target_ids = _safe_id_list(story.get("target_word_ids"))
        session_stories.extend(target_ids)
        context.user_data["story_session_word_ids"] = session_stories
        await show_story(query, context, story["id"])
    else:
        await render(
            query,
            "❌ ساخت داستان ناموفق بود. دوباره تلاش کن.",
            reply_markup=back_inline_keyboard("🔙 بازگشت", f"lesson_{lesson_id}"),
        )


# ─── نمایش داستان ─────────────────────────────────────────────────
async def show_story(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    context.user_data["current_story_id"] = story_id
    # ─── ریست سطح راهنمایی ───
    context.user_data["story_hint_level"] = 0

    title = story.get("title_de") or story.get("title_fa") or "داستان"

    # ─── نمایش کلمات هدف با وضعیت ───
    target_ids = _safe_id_list(story.get("target_word_ids"))
    words = db.get_word_objects_by_ids(target_ids) if target_ids else []

    msg = f"📖 <b>{esc(title)}</b>\n{esc(story['text_de'])}"

    if words:
        msg += "\n\n🎯 <b>کلمات این داستان:</b>\n"
        user_id = query.from_user.id
        for w in words[:12]:
            stats = db.get_word_stats_full(user_id, w.id)
            if not stats:
                status = "🆕"
            elif stats.get("phase") == "learning" or stats.get("wrong", 0) > stats.get("correct", 0):
                status = "⚠️"
            else:
                status = "✅"
            msg += f"{status} {esc(w.display_german)}\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔊+📖 همزمان بخوان و بشنو", callback_data=f"story_listen_read:{story_id}")],
        [InlineKeyboardButton("🎧 فقط بشنو (بدون متن)", callback_data=f"story_listen_only:{story_id}")],
        [InlineKeyboardButton("❓ سوالات درک مطلب و واژگان", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("💡 کمک", callback_data=f"story_hint:{story_id}")],
        [InlineKeyboardButton("🧩 کلمات", callback_data=f"story_words:{story_id}")],
        [InlineKeyboardButton("📖 داستان بعدی", callback_data=f"story_next:{story['lesson_id']}")],
        [InlineKeyboardButton("🔙 بازگشت به درس", callback_data=f"lesson_{story['lesson_id']}")],
    ])
    await render(query, msg, reply_markup=kb)


# ─── راهنمای تدریجی (Progressive Hint) ────────────────────────────
async def show_story_hint(query, context, story_id: int):
    """راهنمای تدریجی: سطح ۱ → کلمات سخت، سطح ۲ → خلاصه، سطح ۳ → ترجمه کامل."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    hint_level = context.user_data.get("story_hint_level", 0)
    user_id = query.from_user.id

    if hint_level == 0:
        # ─── سطح ۱: معنی ۳ کلمه‌ی سخت ───
        target_ids = _safe_id_list(story.get("target_word_ids"))
        words = db.get_word_objects_by_ids(target_ids) if target_ids else []

        # پیدا کردن ۳ کلمه‌ای که کاربر ضعیف‌تر است
        weak_in_story = []
        for w in words:
            stats = db.get_word_stats_full(user_id, w.id)
            if not stats:
                weak_in_story.append(w)
            elif stats.get("wrong", 0) > stats.get("correct", 0):
                weak_in_story.append(w)

        if not weak_in_story:
            weak_in_story = words[:3]

        msg = "💡 <b>راهنمایی سطح ۱: کلمات کلیدی</b>\n\n"
        for w in weak_in_story[:3]:
            msg += f"🔹 <b>{esc(w.display_german)}</b> = {esc(w.persian)}\n"
        msg += "\n📖 حالا دوباره داستان را بخوان."

        context.user_data["story_hint_level"] = 1

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
            [InlineKeyboardButton("💡 کمک بیشتر", callback_data=f"story_hint:{story_id}")],
        ])
        await render(query, msg, reply_markup=kb)

    elif hint_level == 1:
        # ─── سطح ۲: خلاصه‌ی فارسی ───
        title_fa = story.get("title_fa") or story.get("title_de") or "داستان"
        text_fa = story.get("text_fa") or ""

        # خلاصه: فقط ۲-۳ جمله اول
        sentences = text_fa.split(".")
        summary = ". ".join(sentences[:3]) + "." if len(sentences) > 3 else text_fa

        msg = (
            f"💡 <b>راهنمایی سطح ۲: خلاصه‌ی فارسی</b>\n\n"
            f"📌 {esc(title_fa)}\n"
            f"{esc(summary)}\n\n"
            f"📖 حالا سعی کن متن آلمانی را دوباره بخوانی."
        )

        context.user_data["story_hint_level"] = 2

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
            [InlineKeyboardButton("💡 ترجمه کامل", callback_data=f"story_hint:{story_id}")],
        ])
        await render(query, msg, reply_markup=kb)

    else:
        # ─── سطح ۳: ترجمه کامل ───
        await show_story_translation(query, context, story_id)
        # بعد از ترجمه کامل، hint_level ریست نمی‌شود


# ─── ترجمه کامل ───────────────────────────────────────────────────
async def show_story_translation(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    title = story.get("title_fa") or story.get("title_de") or "داستان"
    text_fa = story.get("text_fa") or "ترجمه‌ای موجود نیست."

    msg = f"🇮🇷 <b>ترجمه: {esc(title)}</b>\n{esc(text_fa)}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇩🇪 متن آلمانی", callback_data=f"story_view:{story_id}")],
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("📖 داستان بعدی", callback_data=f"story_next:{story['lesson_id']}")],
    ])
    await render(query, msg, reply_markup=kb)


# ─── Listen & Read ────────────────────────────────────────────────
async def play_story_listen_read(query, context, story_id: int):
    """متن نمایش داده شود + همزمان صوت پخش شود."""
    story = db.get_story(story_id)
    if not story:
        try:
            await query.answer("❌ داستان پیدا نشد.", show_alert=True)
        except Exception:
            pass
        return

    # ابتدا متن را نمایش بده
    title = story.get("title_de") or "داستان"
    msg = (
        f"🔊+📖 <b>همزمان بخوان و بشنو</b>\n\n"
        f"📖 <b>{esc(title)}</b>\n"
        f"{esc(story['text_de'])}\n\n"
        f"🎧 صدا در حال پخش است. همراه با متن گوش بده."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎧 حالا فقط بشنو (بدون متن)", callback_data=f"story_listen_only:{story_id}")],
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
    ])
    await render(query, msg, reply_markup=kb)

    # پخش صدا
    clean_text = re.sub(r"\s*\([^)]*[\u0600-\u06FF][^)]*\)", "", story["text_de"]).strip()
    if not clean_text:
        clean_text = story["text_de"]

    audio_path = await tts.get_audio_path(clean_text)
    if audio_path:
        try:
            with open(audio_path, "rb") as f:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=f,
                    title=title,
                    performer="German Bot",
                    reply_to_message_id=query.message.message_id,
                    allow_sending_without_reply=True,
                )
        except Exception as e:
            logger.error("خطا در پخش صدای Listen & Read: %s", e)


# ─── Listen Only ──────────────────────────────────────────────────
async def play_story_listen_only(query, context, story_id: int):
    """فقط صوت پخش شود، متن مخفی باشد."""
    story = db.get_story(story_id)
    if not story:
        try:
            await query.answer("❌ داستان پیدا نشد.", show_alert=True)
        except Exception:
            pass
        return

    msg = (
        f"🎧 <b>فقط بشنو</b>\n\n"
        f"چشم‌هایت را ببند و فقط گوش بده.\n"
        f"بعد از گوش دادن، دکمه‌ی زیر را بزن تا متن را ببینی."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ حالا متن را ببین", callback_data=f"story_view:{story_id}")],
        [InlineKeyboardButton("🔊 دوباره بشنو", callback_data=f"story_listen_only:{story_id}")],
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
    ])
    await render(query, msg, reply_markup=kb)

    # پخش صدا
    clean_text = re.sub(r"\s*\([^)]*[\u0600-\u06FF][^)]*\)", "", story["text_de"]).strip()
    if not clean_text:
        clean_text = story["text_de"]

    audio_path = await tts.get_audio_path(clean_text)
    if audio_path:
        try:
            with open(audio_path, "rb") as f:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=f,
                    title=story.get("title_de") or "داستان",
                    performer="German Bot",
                    reply_to_message_id=query.message.message_id,
                    allow_sending_without_reply=True,
                )
        except Exception as e:
            logger.error("خطا در پخش صدای Listen Only: %s", e)


# ─── کلمات داستان ─────────────────────────────────────────────────
async def show_story_words(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    target_ids = _safe_id_list(story.get("target_word_ids"))
    words = db.get_word_objects_by_ids(target_ids) if target_ids else []
    user_id = query.from_user.id

    if not words:
        msg = "📭 کلمه‌ای برای این داستان ثبت نشده."
    else:
        msg = f"🧩 <b>کلمات داستان ({len(words)} کلمه)</b>\n"
        for w in words[:15]:
            stats = db.get_word_stats_full(user_id, w.id)
            if not stats:
                status = "🆕 جدید"
            elif stats.get("phase") == "learning":
                status = "⚠️ در حال یادگیری"
            elif stats.get("wrong", 0) > stats.get("correct", 0):
                status = "❌ ضعیف"
            else:
                status = "✅ مسلط"

            line = f"🔹 <b>{esc(w.display_german)}</b> — {esc(w.persian)} [{status}]"
            if w.example_de:
                line += f"\n   📝 {esc(w.example_de)}"
            msg += line + "\n"

        if len(words) > 15:
            msg += f"... و {len(words) - 15} کلمه دیگر"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
    ])
    await render(query, msg, reply_markup=kb)


# ─── کوییز داستان ─────────────────────────────────────────────────
async def start_story_quiz(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    questions = _safe_json_list(story.get("questions_json"))
    questions = [q for q in questions if isinstance(q, dict) and q.get("question")]

    if not questions:
        await render(
            query,
            "📭 سوالی برای این داستان ثبت نشده.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
            ]),
        )
        return

    # ─── جداسازی Comprehension و Vocabulary ───
    comprehension_qs = [q for q in questions if q.get("question_type") == "comprehension"]
    vocabulary_qs = [q for q in questions if q.get("question_type") == "vocabulary"]

    # اگر question_type ندارند، همه را comprehension فرض کن
    if not comprehension_qs and not vocabulary_qs:
        comprehension_qs = questions

    # ترتیب: اول comprehension، بعد vocabulary
    ordered_questions = comprehension_qs + vocabulary_qs

    context.user_data["story_quiz"] = {
        "story_id": story_id,
        "questions": ordered_questions,
        "current": 0,
        "correct": 0,
        "wrong": 0,
        "comprehension_correct": 0,
        "comprehension_wrong": 0,
        "vocabulary_correct": 0,
        "vocabulary_wrong": 0,
    }

    await _show_story_question(query, context)


async def _show_story_question(query, context):
    quiz = context.user_data.get("story_quiz")
    if not quiz:
        await render(query, "⚠️ کوییز فعال نیست.", reply_markup=back_inline_keyboard())
        return

    q = quiz["questions"][quiz["current"]]
    options = list(q.get("options") or [])
    correct = str(q.get("correct_answer") or q.get("correct") or "").strip()

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

    # ─── برچسب نوع سوال ───
    q_type = q.get("question_type", "comprehension")
    type_label = "📖 درک مطلب" if q_type == "comprehension" else "🧠 واژگان"

    msg = f"❓ <b>سوال {num} از {total}</b> [{type_label}]\n{esc(q['question'])}"

    kb = []
    for i, opt in enumerate(options):
        label = f"{chr(65 + i)}) {opt}"
        kb.append([InlineKeyboardButton(_short_label(label, 64), callback_data=f"story_ans:{i}")])

    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb))


# ─── پاسخ به سوال داستان ──────────────────────────────────────────
async def handle_story_answer(query, context, suffix: str):
    quiz = context.user_data.get("story_quiz")
    if not quiz:
        try:
            await query.answer("⚠️ کوییز فعال نیست.", show_alert=True)
        except Exception:
            pass
        return

    try:
        chosen = int(suffix)
    except ValueError:
        return

    options = quiz.get("current_options", [])
    if chosen < 0 or chosen >= len(options):
        return

    q = quiz["questions"][quiz["current"]]
    correct_idx = quiz.get("current_correct_index", -1)
    is_correct = chosen == correct_idx
    correct_answer = options[correct_idx] if 0 <= correct_idx < len(options) else "?"

    user_id = query.from_user.id
    story_id = quiz["story_id"]
    word_id = q.get("word_id")
    q_type = q.get("question_type", "comprehension")

    # ─── 1. آپدیت آمار کلی ───
    db.update_quiz_stats(user_id, is_correct)

    # ─── 2. آپدیت پیشرفت داستان ───
    db.learning.record_story_answer(user_id, story_id, is_correct)

    # ─── 3. آمار تفکیکی ───
    if q_type == "comprehension":
        if is_correct:
            quiz["comprehension_correct"] += 1
        else:
            quiz["comprehension_wrong"] += 1
    else:  # vocabulary
        if is_correct:
            quiz["vocabulary_correct"] += 1
        else:
            quiz["vocabulary_wrong"] += 1

    # ─── 4. فقط Vocabulary questions روی FSRS اثر بگذارند ───
    if q_type == "vocabulary" and word_id:
        db.learning.record_skill(user_id, word_id, "reading", is_correct)

        # FSRS فقط برای vocab questions
        from srs_service import FSRSService
        fsrs_service = FSRSService(db)
        grade = 3 if is_correct else 1
        fsrs_service.review(user_id, word_id, grade)

    # ─── 5. ثبت اشتباه ───
    if not is_correct:
        db.learning.record_mistake(
            user_id=user_id,
            word_id=word_id if q_type == "vocabulary" else None,
            story_id=story_id,
            skill_type="reading" if q_type == "vocabulary" else "story",
            quiz_type="story",
            user_answer=options[chosen],
            correct_answer=correct_answer,
        )

    if is_correct:
        quiz["correct"] += 1
        try:
            await query.answer("✅ درست!", show_alert=False)
        except Exception:
            pass
    else:
        quiz["wrong"] += 1
        try:
            await query.answer(f"❌ جواب: {correct_answer}", show_alert=True)
        except Exception:
            pass

    quiz["current"] += 1

    if quiz["current"] >= len(quiz["questions"]):
        await _show_story_quiz_summary(query, context)
    else:
        await _show_story_question(query, context)


# ─── خلاصه کوییز داستان ──────────────────────────────────────────
async def _show_story_quiz_summary(query, context):
    quiz = context.user_data.pop("story_quiz", None)
    if not quiz:
        await render(query, "🏁 کوییز تمام شد.", reply_markup=back_inline_keyboard())
        return

    story_id = quiz["story_id"]
    story = db.get_story(story_id)
    lesson_id = story["lesson_id"] if story else None

    total = len(quiz["questions"])
    correct = quiz["correct"]
    wrong = quiz["wrong"]
    accuracy = (correct / total * 100) if total > 0 else 0

    # ─── آمار تفکیکی ───
    comp_correct = quiz.get("comprehension_correct", 0)
    comp_wrong = quiz.get("comprehension_wrong", 0)
    comp_total = comp_correct + comp_wrong
    comp_acc = int(comp_correct / comp_total * 100) if comp_total else 0

    vocab_correct = quiz.get("vocabulary_correct", 0)
    vocab_wrong = quiz.get("vocabulary_wrong", 0)
    vocab_total = vocab_correct + vocab_wrong
    vocab_acc = int(vocab_correct / vocab_total * 100) if vocab_total else 0

    db.record_activity(query.from_user.id, 5 * correct)

    msg = (
        f"🏁 <b>کوییز داستان تمام شد!</b>\n"
        f"✅ درست: {correct}\n"
        f"❌ اشتباه: {wrong}\n"
        f"🎯 دقت کل: {accuracy:.0f}%\n\n"
        f"📖 درک مطلب: {comp_correct}/{comp_total} ({comp_acc}%)\n"
        f"🧠 واژگان: {vocab_correct}/{vocab_total} ({vocab_acc}%)\n\n"
    )

    if accuracy == 100:
        msg += "🌟 عالی! داستان را کامل فهمیدی!"
    elif accuracy >= 60:
        msg += "👍 خوب بود! یک بار دیگر داستان را بخوان."
    else:
        msg += "💡 پیشنهاد: داستان را دوباره با «همزمان بخوان و بشنو» تمرین کن."

    kb_buttons = []

    # ─── Story Replay: اگر دقت زیر ۶۰٪ بود ───
    if accuracy < 60:
        kb_buttons.append([
            InlineKeyboardButton("🔄 Replay با راهنمایی", callback_data=f"story_replay:{story_id}")
        ])
    else:
        kb_buttons.append([
            InlineKeyboardButton("📖 خواندن دوباره", callback_data=f"story_view:{story_id}")
        ])

    kb_buttons.append([
        InlineKeyboardButton("❓ کوییز دوباره", callback_data=f"story_quiz:{story_id}")
    ])

    if lesson_id:
        kb_buttons.append([
            InlineKeyboardButton("📖 داستان بعدی", callback_data=f"story_next:{lesson_id}")
        ])

    kb_buttons.append([
        InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")
    ])

    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))


# ─── Story Replay ─────────────────────────────────────────────────
async def replay_story(query, context, story_id: int):
    """بازپخش داستان با حالت Listen & Read برای تقویت."""
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    # ریست hint level
    context.user_data["story_hint_level"] = 0

    title = story.get("title_de") or "داستان"

    msg = (
        f"🔄 <b>Replay: {esc(title)}</b>\n\n"
        f"این بار با دقت بیشتری بخوان و گوش بده.\n"
        f"سعی کن کلماتی که در کوییز اشتباه زدی را پیدا کنی.\n\n"
        f"📖 {esc(story['text_de'])}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔊+📖 همزمان بخوان و بشنو", callback_data=f"story_listen_read:{story_id}")],
        [InlineKeyboardButton("🎧 فقط بشنو", callback_data=f"story_listen_only:{story_id}")],
        [InlineKeyboardButton("💡 کمک", callback_data=f"story_hint:{story_id}")],
        [InlineKeyboardButton("❓ کوییز دوباره", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("📖 داستان بعدی", callback_data=f"story_next:{story['lesson_id']}")],
    ])
    await render(query, msg, reply_markup=kb)