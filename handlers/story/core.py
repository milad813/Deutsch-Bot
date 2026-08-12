"""Core story generation logic."""

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
MAX_STORY_WORDS = 5        # کلماتی که واقعاً در داستان استفاده می‌شوند
MAX_CANDIDATE_WORDS = 10   # کلماتی که به LLM Planning داده می‌شوند
MIN_STORY_WORDS = 3        # حداقل کلمات برای یک داستان معنادار

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
    """نسبت (new, weak, mastered) بر اساس سطح."""
    if level == "A1":
        return 0.3, 0.5, 0.2
    elif level == "A2":
        return 0.4, 0.4, 0.2
    else:
        return 0.5, 0.3, 0.2


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


# ─── انتخاب هوشمند کلمات (Candidate Pool) ────────────────────────
def _select_smart_words(
    user_id: int, lesson_id: int, exclude_ids: Set[int], level: str = "A1"
) -> List[Dict]:
    """انتخاب هوشمند کلمات با استفاده از metadata جدید."""
    all_words = db.get_words_by_lesson_full(lesson_id)
    if not all_words:
        return []

    # ─── فیلتر ۱: فقط کلمات story-friendly ───
    story_friendly = [
        w for w in all_words
        if w.get("word_type") in STORY_WORD_TYPES
        and (w.get("story_suitability") or 3) >= 3
    ]

    if not story_friendly:
        story_friendly = [
            w for w in all_words if w.get("word_type") in STORY_WORD_TYPES
        ]

    # ─── دسته‌بندی new/weak/mastered ───
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

    # ─── محاسبه تعداد بر اساس نسبت ───
    new_ratio, weak_ratio, mastered_ratio = _get_word_ratios(level)
    total = min(MAX_CANDIDATE_WORDS, len(story_friendly))

    n_new = max(1, int(total * new_ratio))
    n_weak = max(1, int(total * weak_ratio))
    n_mastered = max(0, total - n_new - n_weak)

    # ─── نمونه‌گیری ───
    selected = []
    selected.extend(random.sample(new_words, min(n_new, len(new_words))))
    selected.extend(random.sample(weak_words, min(n_weak, len(weak_words))))
    selected.extend(random.sample(mastered_words, min(n_mastered, len(mastered_words))))

    # ─── شافل و برگرداندن ───
    random.shuffle(selected)
    return selected[:MAX_CANDIDATE_WORDS]


def _select_genre(level: str, lesson_title: str) -> Dict:
    """انتخاب ژانر بر اساس سطح و موضوع درس."""
    allowed = GENRE_BY_LEVEL.get(level, GENRE_BY_LEVEL["A1"])
    genre_id = random.choice(allowed)
    return next((g for g in GENRES if g["id"] == genre_id), GENRES[0])


def _get_adaptive_level(user_id: int, lesson_level: str) -> str:
    """تعیین سطح تطبیقی بر اساس عملکرد کاربر."""
    recent_stats = db.get_recent_performance(user_id, days=7)
    if not recent_stats:
        return lesson_level

    accuracy = recent_stats.get("accuracy", 0.5)
    if accuracy > 0.8 and lesson_level in ["A1", "A2"]:
        return "B1"
    elif accuracy < 0.4 and lesson_level in ["B1", "B2"]:
        return "A2"
    return lesson_level


async def _plan_story(words: List[Dict], level: str, lesson_title: str) -> Optional[Dict]:
    """LLM Planning: طراحی ساختار داستان."""
    if not words or len(words) < MIN_STORY_WORDS:
        return None

    word_list = "\n".join([
        f"- {w['display_german']} ({w['persian']}) — {w.get('word_type', '')}"
        for w in words[:MAX_STORY_WORDS]
    ])

    prompt = f"""
Du bist ein erfahrener Deutschlehrer und Geschichtenerzähler.

**Ziel:** Erstelle eine kurze, natürliche Geschichte auf Niveau {level}.

**Wortschatz aus Lektion "{lesson_title}":**
{word_list}

**Anforderungen:**
1. Verwende NUR die oben genannten Wörter (max. 5).
2. Die Geschichte muss logisch und natürlich klingen.
3. Länge: 80–120 Wörter.
4. Thema: Alltagssituation oder kleines Abenteuer.

**Ausgabeformat (JSON):**
{{
  "title": "...",
  "text": "...",
  "used_words": [word_id1, word_id2],
  "genre": "daily|adventure|mystery|humor|social",
  "level": "{level}"
}}
""".strip()

    try:
        response = await llm.generate(prompt, temperature=0.7, max_tokens=500)
        raw = response.strip()

        # ─── استخراج JSON ───
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            logger.warning("JSON nicht gefunden: %s", raw[:100])
            return None

        plan = json.loads(match.group())
        if not isinstance(plan, dict) or "text" not in plan:
            return None

        # ─── اعتبارسنجی اولیه ───
        used = plan.get("used_words", [])
        if not isinstance(used, list) or len(used) < MIN_STORY_WORDS:
            return None

        return plan

    except Exception as e:
        logger.error("خطا در برنامه‌ریزی داستان: %s", e)
        return None


def _filter_words_by_plan(words: List[Dict], plan: Dict) -> List[Dict]:
    """فیلتر کلمات بر اساس plan."""
    used_ids = set(plan.get("used_words", []))
    return [w for w in words if w["id"] in used_ids]


def _build_enhanced_prompt(
    words: List[Dict], level: str, lesson_title: str, genre: Dict
) -> str:
    """ساخت پرامپت نهایی برای تولید داستان."""
    word_details = "\n".join([
        f"- {w['display_german']} ({w['persian']}) — {w.get('word_type', '')}\n"
        f"  Beispiel: {w.get('example_de', 'N/A')} → {w.get('example_fa', 'N/A')}"
        for w in words
    ])

    return f"""
Du bist ein erfahrener Deutschlehrer und kreativer Geschichtenerzähler.

**Aufgabe:** Schreibe eine kurze, fesselnde Geschichte für Deutschlernende.

**Niveau:** {level} (GER)
**Genre:** {genre['de']} ({genre['fa']}) – {genre['desc']}
**Lektion:** {lesson_title}

**Wortschatz (verwende ALLE diese Wörter):**
{word_details}

**Anforderungen:**
1. **Länge:** 100–150 Wörter
2. **Stil:** Einfach, klar, natürlich – wie eine echte Alltagssituation
3. **Struktur:**
   - Einleitung (Setting + Charaktere)
   - Hauptteil (Konflikt oder Ereignis)
   - Schluss (Lösung oder Erkenntnis)
4. **Hervorhebung:** Markiere die Zielwörter mit **Fett**
5. **Keine zusätzlichen schwierigen Wörter** – bleibe im Niveau {level}

**Ausgabeformat (JSON):**
{{
  "title": "Kurzer Titel (max. 6 Wörter)",
  "text": "Der vollständige Text mit **markierten** Wörtern",
  "target_word_ids": [123, 456, 789],
  "questions": [
    {{
      "q": "Frage zum Verständnis?",
      "options": ["Antwort A", "Antwort B", "Antwort C", "Antwort D"],
      "correct_index": 0
    }}
  ],
  "genre": "{genre['id']}",
  "level": "{level}"
}}

**Hinweis:** Die Fragen sollten das Verständnis der Geschichte prüfen, nicht nur Details abfragen.
""".strip()


async def _validate_story_naturalness(
    story_text: str, words: List[Dict], level: str
) -> bool:
    """بررسی طبیعی بودن داستان."""
    if len(story_text.split()) < 50:
        return False

    word_count = sum(
        1 for w in words
        if w["german"].lower() in story_text.lower()
    )
    return word_count >= MIN_STORY_WORDS


async def _generate_story_for_lesson(
    user_id: int, lesson_id: int, exclude_ids: Set[int]
) -> Optional[Dict]:
    """تابع اصلی تولید داستان هوشمند."""
    lesson = db.get_lesson(lesson_id)
    if not lesson:
        return None

    level = _get_adaptive_level(user_id, lesson["level"])
    genre = _select_genre(level, lesson["title"])

    logger.info(
        "📖 شروع ساخت داستان: درس %d (%s)، سطح %s، ژانر %s",
        lesson_id, lesson["title"], level, genre["fa"]
    )

    # ─── انتخاب هوشمند کلمات ───
    candidate_words = _select_smart_words(user_id, lesson_id, exclude_ids, level)
    if len(candidate_words) < MIN_STORY_WORDS:
        logger.warning("کلمات کافی یافت نشد: %d < %d", len(candidate_words), MIN_STORY_WORDS)
        return None

    # ─── Planning با LLM ───
    plan = await _plan_story(candidate_words, level, lesson["title"])
    if not plan:
        logger.warning("Planning ناموفق بود")
        return None

    # ─── فیلتر کلمات بر اساس plan ───
    target_words = _filter_words_by_plan(candidate_words, plan)
    if len(target_words) < MIN_STORY_WORDS:
        logger.warning("کلمات فیلترشده کافی نیستند: %d", len(target_words))
        target_words = candidate_words[:MAX_STORY_WORDS]

    # ─── تولید داستان نهایی ───
    prompt = _build_enhanced_prompt(target_words, level, lesson["title"], genre)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = await llm.generate(prompt, temperature=0.7, max_tokens=800)
            raw = response.strip()

            # ─── استخراج JSON ───
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                logger.warning("JSON پیدا نشد (تلاش %d)", attempt + 1)
                continue

            story_data = json.loads(match.group())

            # ─── اعتبارسنجی ───
            if not all(k in story_data for k in ["title", "text", "target_word_ids", "questions"]):
                logger.warning("کلیدهای ضروری缺失 (تلاش %d)", attempt + 1)
                continue

            questions = story_data.get("questions", [])
            valid_q = [
                q for q in questions
                if isinstance(q, dict)
                and "q" in q and "options" in q and "correct_index" in q
                and len(q["options"]) == 4
            ]

            if len(valid_q) < 2:
                logger.warning("سوالات کافی نیست: %d (تلاش %d)", len(valid_q), attempt + 1)
                continue

            # ─── بررسی طبیعی بودن ───
            is_natural = await _validate_story_naturalness(
                story_data["text"], target_words, level
            )
            if not is_natural:
                logger.warning("داستان طبیعی نیست (تلاش %d)", attempt + 1)
                continue

            # ─── ذخیره در دیتابیس ───
            story_id = db.create_story(
                lesson_id=lesson_id,
                title=story_data["title"],
                text_de=story_data["text"],
                text_fa="",  # بعداً توسط مترجم پر می‌شود
                target_word_ids=json.dumps([w["id"] for w in target_words]),
                questions_json=json.dumps(valid_q, ensure_ascii=False),
                level=level,
            )

            logger.info(
                "✅ داستان id=%d برای درس %d (%d کلمه، %d سوال، ژانر: %s، سری: %d/%d)",
                story_id, lesson_id, len(target_words), len(valid_q),
                genre["fa"], attempt + 1, max_retries,
            )
            return db.get_story(story_id)

        except Exception as e:
            logger.warning("خطا در ساخت داستان (تلاش %d): %s", attempt + 1, e)
            continue

    return None


async def show_story_menu(query, context, lesson_id: int):
    """منوی داستان - همیشه تولید داستان جدید."""
    from handlers.story.view import show_story
    
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
