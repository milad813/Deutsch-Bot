"""Core story generation logic."""

import json
import logging
import random
import re
from typing import Dict, List, Optional, Set

from services import db, llm
from ui import back_inline_keyboard, render
from utils import safe_id_list

logger = logging.getLogger(__name__)


# ─── تنظیمات داستان هوشمند ───────────────────────────────────────
STORY_WORD_TYPES = ("Noun", "Verb", "Adjective")
MAX_STORY_WORDS = 5  # کلماتی که واقعاً در داستان استفاده می‌شوند
MAX_CANDIDATE_WORDS = 10  # کلماتی که به LLM Planning داده می‌شوند
MIN_STORY_WORDS = 3  # حداقل کلمات برای یک داستان معنادار


# ─── ژانرها ───────────────────────────────────────────────────────
GENRES = [
    {"id": "daily", "de": "Alltag", "fa": "روزمره", "desc": "موقعیت‌های عادی زندگی"},
    {
        "id": "adventure",
        "de": "Abenteuer",
        "fa": "ماجراجویی",
        "desc": "سفر یا اتفاق هیجان‌انگیز",
    },
    {"id": "mystery", "de": "Rätsel", "fa": "معمایی", "desc": "حل یک مشکل یا معما"},
    {"id": "humor", "de": "Humor", "fa": "طنز", "desc": "اتفاق خنده‌دار یا غیرمنتظره"},
    {
        "id": "social",
        "de": "Sozial",
        "fa": "اجتماعی",
        "desc": "دیدار با دوستان یا خانواده",
    },
]

# ─── ژانر مجاز بر اساس سطح ───────────────────────────────────────
GENRE_BY_LEVEL = {
    "A1": ["daily", "social"],
    "A2": ["daily", "social", "humor"],
    "B1": ["daily", "social", "humor", "adventure"],
    "B2": [g["id"] for g in GENRES],
}


# ─── توابع کمکی ──────────────────────────────────────────────────
def _get_display_german(w: dict) -> str:
    """ساخت display_german از روی دیکشنری کلمه.

    چون خروجی db.words.get_by_lesson_full() یک dict است (نه آبجکت Word)،
    property display_german روی آن وجود ندارد و باید دستی ساخته شود.
    """
    article = (w.get("article") or "").strip()
    german = (w.get("german") or "").strip()
    return f"{article} {german}".strip() if article else german


def _get_word_ratios(level: str) -> tuple:
    """نسبت (new, weak, mastered) بر اساس سطح."""
    if level == "A1":
        return 0.3, 0.5, 0.2
    elif level == "A2":
        return 0.4, 0.4, 0.2
    else:
        return 0.5, 0.3, 0.2


def _format_story_text(text: str, words: List[Dict]) -> str:
    """پاکسازی خروجی LLM و بولد کردن دقیق کلمات با تگ HTML."""
    # 1. حذف تمام ** های مارک‌داون که LLM اشتباهی تولید کرده
    clean_text = text.replace("**", "")

    # 2. بولد کردن کلمات هدف با تگ <b> (پشتیبانی از صرف فعل/صفت)
    for w in words:
        german = w.get("german", "")
        if not german:
            continue

        # پیدا کردن کلمه و پسوندهای احتمالی (مثل schlechten برای schlecht)
        # re.IGNORECASE برای حساس نبودن به حروف بزرگ/کوچک
        pattern = re.compile(rf"\b({re.escape(german)}[a-zäöüß]*)\b", re.IGNORECASE)
        clean_text = pattern.sub(r"<b>\1</b>", clean_text)

    return clean_text


# ─── انتخاب هوشمند کلمات (Candidate Pool) ────────────────────────
def _story_suitability_score(w: Dict) -> int:
    value = w.get("story_suitability")
    if value is None:
        return 3
    try:
        return int(value)
    except Exception:
        return 3

def _select_smart_words(
    user_id: int, lesson_id: int, exclude_ids: Set[int], level: str = "A1"
) -> List[Dict]:
    """انتخاب هوشمند کلمات با استفاده از metadata جدید."""
    all_words = db.words.get_by_lesson_full(lesson_id)
    if not all_words:
        return []

    # ─── فیلتر ۱: فقط کلمات story-friendly ───
    story_friendly = [
        w
        for w in all_words
        if w.get("word_type") in STORY_WORD_TYPES
        and _story_suitability_score(w) >= 3
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

        stats = db.words.get_stats_full(user_id, wid)
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

    if total <= 0:
        return []

    n_new = max(1, int(total * new_ratio))
    n_weak = max(1, int(total * weak_ratio))
    n_mastered = max(0, total - n_new - n_weak)

    # ─── نمونه‌گیری ───
    selected = []
    selected.extend(random.sample(new_words, min(n_new, len(new_words))))
    selected.extend(random.sample(weak_words, min(n_weak, len(weak_words))))
    selected.extend(
        random.sample(mastered_words, min(n_mastered, len(mastered_words)))
    )

    # اگر انتخاب‌ها کمتر از حداقل بودند، از بقیه story_friendly پر کن
    if len(selected) < MIN_STORY_WORDS:
        selected_ids = {w["id"] for w in selected}
        for w in story_friendly:
            if w["id"] not in selected_ids:
                selected.append(w)
                selected_ids.add(w["id"])
            if len(selected) >= MIN_STORY_WORDS:
                break

    random.shuffle(selected)
    return selected[:MAX_CANDIDATE_WORDS]

def _select_genre(level: str, lesson_title: str) -> Dict:
    """انتخاب ژانر بر اساس سطح و موضوع درس."""
    allowed = GENRE_BY_LEVEL.get(level, GENRE_BY_LEVEL["A1"])
    genre_id = random.choice(allowed)
    return next((g for g in GENRES if g["id"] == genre_id), GENRES[0])


def _get_adaptive_level(user_id: int, lesson_level: str) -> str:
    """تعیین سطح تطبیقی بر اساس عملکرد کاربر."""
    # استفاده از get_weekly_stats که آمار ۷ روز اخیر را برمی‌گرداند
    recent_stats = db.learning.get_weekly_stats(user_id)

    # اگر کاربر هیچ فعالیتی نداشته، همان سطح درس را برگردان
    if not recent_stats or recent_stats.get("total_answers", 0) == 0:
        return lesson_level

    # get_weekly_stats دقت را به صورت درصد (0-100) برمی‌گرداند
    accuracy = recent_stats.get("accuracy", 50)

    # تنظیم سطح بر اساس دقت کاربر
    LEVEL_ORDER = ["A1", "A2", "B1", "B2"]

    if accuracy > 80:
        idx = LEVEL_ORDER.index(lesson_level) if lesson_level in LEVEL_ORDER else 0
        if idx < len(LEVEL_ORDER) - 1:
            return LEVEL_ORDER[idx + 1]
    elif accuracy < 40 and lesson_level in ["B1", "B2"]:
        return "A2"

    return lesson_level

async def _plan_story(
    words: List[Dict], level: str, lesson_title: str
) -> Optional[Dict]:
    """LLM Planning: طراحی ساختار داستان."""
    if not words or len(words) < MIN_STORY_WORDS:
        return None

    word_list = "\n".join(
        [
            f"- id={w['id']} | {_get_display_german(w)} ({w['persian']}) — {w.get('word_type', '')}"
            for w in words[:MAX_CANDIDATE_WORDS]
        ]
    )

    prompt = f"""
Du bist ein erfahrener Deutschlehrer und Geschichtenerzähler.

**Ziel:** Erstelle eine kurze, natürliche Geschichte auf Niveau {level}.

**Wortschatz aus Lektion "{lesson_title}":**
{word_list}

**Anforderungen:**
1. Wähle maximal {MAX_STORY_WORDS} Wörter aus der Liste aus.
2. Die Geschichte muss logisch und natürlich klingen.
3. Länge: 80–120 Wörter.
4. Thema: Alltagssituation oder kleines Abenteuer.
5. Gib in "used_words" NUR die id-Zahlen der ausgewählten Wörter zurück.

**Ausgabeformat (JSON):**
{{
  "title": "...",
  "text": "...",
  "used_words": [12, 34, 56],
  "genre": "daily|adventure|mystery|humor|social",
  "level": "{level}"
}}
""".strip()

    try:
        response = await llm._chat(
            "You are a German teacher. You output only valid JSON.",
            prompt,
            temperature=0.7,
            max_tokens=1024,
        )
        if not response:
            return None

        raw = response.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            logger.warning("JSON nicht gefunden: %s", raw[:200])
            return None

        plan = json.loads(match.group())
        if not isinstance(plan, dict) or "text" not in plan:
            return None

        used = []
        for item in plan.get("used_words", []):
            try:
                used.append(int(item))
            except Exception:
                continue

        # حذف duplicateها
        seen = set()
        unique_used = []
        for word_id in used:
            if word_id not in seen:
                seen.add(word_id)
                unique_used.append(word_id)

        plan["used_words"] = unique_used[:MAX_STORY_WORDS]

        if len(plan["used_words"]) < MIN_STORY_WORDS:
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
    word_details = "\n".join(
        [
            f"- id={w['id']} | {_get_display_german(w)} ({w['persian']}) — {w.get('word_type', '')}\n"
            f"  Beispiel: {w.get('example_de', 'N/A')} → {w.get('example_fa', 'N/A')}"
            for w in words
        ]
    )

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
2. **Grammatik (WICHTIG für A1):** Verwende NUR Präsens (Gegenwart). KEIN Präteritum (z.B. wollte, musste, fuhr), KEIN Plusquamperfekt. Nutze einfache Sätze.
3. **Stil:** Einfach, klar, natürlich – wie eine echte Alltagssituation
4. **Struktur:**
   - Einleitung (Setting + Charaktere)
   - Hauptteil (Konflikt oder Ereignis)
   - Schluss (Lösung oder Erkenntnis)
5. **Hervorhebung:** Markiere die Zielwörter mit HTML-Tags: <b>Wort</b> (NICHT mit ** Sternchen)
6. **Keine zusätzlichen schwierigen Wörter** – bleibe strikt im Niveau {level}. Benutze nur die 1000 häufigsten deutschen Wörter.
7. Erstelle mindestens 2, höchstens 4 Verständnisfragen.
8. Jede Frage muss genau 4 Optionen haben.
9. Gib bei jeder Frage einen question_type an: comprehension, vocabulary oder detail.

**Ausgabeformat (JSON):**
{{
  "title": "Kurzer Titel (max. 6 Wörter)",
  "text": "Der vollständige Text mit <b>markierten</b> Wörtern",
  "questions": [
    {{
      "q": "Frage zum Verständnis?",
      "options": ["Antwort A", "Antwort B", "Antwort C", "Antwort D"],
      "correct_index": 0,
      "question_type": "comprehension"
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
    word_count = sum(1 for w in words if w["german"].lower() in story_text.lower())
    return word_count >= MIN_STORY_WORDS

async def _generate_story_for_lesson(
    user_id: int, lesson_id: int, exclude_ids: Set[int]
) -> Optional[Dict]:
    """تابع اصلی تولید داستان هوشمند."""
    lesson = db.lessons.get_by_id(lesson_id)
    if not lesson:
        return None

    lesson_title = lesson[2] or f"درس {lesson[1]}"
    book_level = db.books.get_level_by_lesson(lesson_id) or "A1"
    level = _get_adaptive_level(user_id, book_level)
    genre = _select_genre(level, lesson_title)

    logger.info(
        "📖 شروع ساخت داستان: درس %d (%s)، سطح %s، ژانر %s",
        lesson_id,
        lesson_title,
        level,
        genre["fa"],
    )

    # ─── انتخاب هوشمند کلمات ───
    candidate_words = _select_smart_words(user_id, lesson_id, exclude_ids, level)
    if len(candidate_words) < MIN_STORY_WORDS:
        logger.warning(
            "کلمات کافی یافت نشد: %d < %d",
            len(candidate_words),
            MIN_STORY_WORDS,
        )
        return None

    # ─── Planning با LLM ───
    plan = await _plan_story(candidate_words, level, lesson_title)

    target_words = []
    if plan:
        target_words = _filter_words_by_plan(candidate_words, plan)

    # اگر plan ناموفق بود یا کلمات کافی پیدا نشد، fallback مستقیم
    if len(target_words) < MIN_STORY_WORDS:
        logger.warning(
            "کلمات فیلترشده کافی نیستند یا plan ناموفق بود. fallback: %d",
            len(target_words),
        )
        target_words = candidate_words[:MAX_STORY_WORDS]

    # ─── تولید داستان نهایی ───
    prompt = _build_enhanced_prompt(target_words, level, lesson_title, genre)
    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = await llm._chat(
                "You are a creative German language teacher. You output only valid JSON.",
                prompt,
                temperature=0.7,
                max_tokens=2048,
            )

            if not response:
                logger.warning("LLM پاسخی نداد (تلاش %d)", attempt + 1)
                continue

            raw = response.strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                logger.warning("JSON پیدا نشد (تلاش %d)", attempt + 1)
                continue

            story_data = json.loads(match.group())

            # target_word_ids دیگر از LLM گرفته نمی‌شود.
            # خودمان آن را از target_words می‌سازیم.
            if not all(k in story_data for k in ["title", "text", "questions"]):
                logger.warning("کلیدهای ضروری ناقص هستند (تلاش %d)", attempt + 1)
                continue

            story_data["text"] = _format_story_text(
                story_data["text"], target_words
            )

            questions = story_data.get("questions", [])
            valid_q = []
            allowed_q_types = {"comprehension", "vocabulary", "detail"}

            for q in questions:
                if not isinstance(q, dict):
                    continue

                if "q" not in q or "options" not in q or "correct_index" not in q:
                    continue

                options = q.get("options") or []
                if len(options) != 4:
                    continue

                try:
                    correct_index = int(q.get("correct_index"))
                except Exception:
                    continue

                if correct_index < 0 or correct_index >= len(options):
                    continue

                q["correct_index"] = correct_index

                q_type = str(q.get("question_type") or "comprehension").strip().lower()
                if q_type not in allowed_q_types:
                    q_type = "comprehension"

                q["question_type"] = q_type
                valid_q.append(q)

            if len(valid_q) < 2:
                logger.warning(
                    "سوالات کافی نیست: %d (تلاش %d)",
                    len(valid_q),
                    attempt + 1,
                )
                continue

            # ─── بررسی طبیعی بودن ───
            is_natural = await _validate_story_naturalness(
                story_data["text"], target_words, level
            )
            if not is_natural:
                logger.warning("داستان طبیعی نیست (تلاش %d)", attempt + 1)
                continue

            # ─── تولید ترجمه فارسی ───
            title_fa = ""
            text_fa = ""

            try:
                if llm.is_available():
                    translate_prompt = f"""Translate this German story to Persian. Return ONLY JSON:
{{"title_fa": "...", "text_fa": "..."}}

Title: {story_data.get("title", "")}
Text: {story_data["text"]}"""

                    translate_response = await llm._chat(
                        "You translate German to Persian. Output only valid JSON.",
                        translate_prompt,
                        temperature=0.3,
                        max_tokens=500,
                    )

                    if translate_response:
                        translate_match = re.search(
                            r"\{.*\}", translate_response, re.DOTALL
                        )
                        if translate_match:
                            translate_data = json.loads(translate_match.group())
                            title_fa = str(
                                translate_data.get("title_fa") or ""
                            ).strip()
                            text_fa = str(
                                translate_data.get("text_fa") or ""
                            ).strip()
            except Exception as e:
                logger.warning("خطا در ترجمه داستان: %s", e)

            story_id = db.stories.add(
                lesson_id=lesson_id,
                title_de=story_data.get("title", ""),
                title_fa=title_fa,
                text_de=story_data["text"],
                text_fa=text_fa,
                target_word_ids=json.dumps([w["id"] for w in target_words]),
                questions_json=json.dumps(valid_q, ensure_ascii=False),
                level=level,
            )

            logger.info(
                "✅ داستان id=%d برای درس %d (%d کلمه، %d سوال، ژانر: %s، تلاش: %d/%d)",
                story_id,
                lesson_id,
                len(target_words),
                len(valid_q),
                genre["fa"],
                attempt + 1,
                max_retries,
            )

            return db.stories.get_by_id(story_id)

        except json.JSONDecodeError as e:
            logger.warning("خطای JSON (تلاش %d): %s", attempt + 1, e)
            continue
        except Exception as e:
            logger.warning("خطا در ساخت داستان (تلاش %d): %s", attempt + 1, e)
            continue

    return None

async def show_story_menu(query, context, lesson_id: int):
    """منوی داستان - همیشه تولید داستان جدید."""
    from handlers.story.view import show_story

    user_id = query.from_user.id

    # ✅ جلوگیری از کلیک‌های مکرر
    if context.user_data.get("story_generating"):
        try:
            await query.answer("⏳ در حال ساخت داستان قبلی...", show_alert=True)
        except Exception:
            pass
        return

    if not llm.is_available():
        await render(
            query,
            "❌ قابلیت LLM فعال نیست.\n"
            "در <code>.env</code> کلید <code>GROQ_API_KEY</code> را تنظیم کن.",
            reply_markup=back_inline_keyboard("🔙 بازگشت", f"lesson_{lesson_id}"),
        )
        return

    context.user_data["story_generating"] = True

    try:
        session_stories = context.user_data.get("story_session_word_ids", [])
        exclude_ids = set(session_stories)

        try:
            await query.answer("📖 در حال ساخت داستان جدید...", show_alert=False)
        except Exception:
            pass

        story = await _generate_story_for_lesson(user_id, lesson_id, exclude_ids)

        if story:
            target_ids = safe_id_list(story.get("target_word_ids"))
            session_stories.extend(target_ids)
            context.user_data["story_session_word_ids"] = session_stories
            await show_story(query, context, story["id"])
        else:
            await render(
                query,
                "❌ ساخت داستان ناموفق بود. دوباره تلاش کن.",
                reply_markup=back_inline_keyboard("🔙 بازگشت", f"lesson_{lesson_id}"),
            )
    finally:
        context.user_data.pop("story_generating", None)
