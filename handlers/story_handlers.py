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

    # ─── نسبت‌ها ───
    new_ratio, review_ratio, mastered_ratio = _get_word_ratios(level)
    total_candidates = min(MAX_CANDIDATE_WORDS, len(story_friendly))
    n_new = max(1, int(total_candidates * new_ratio))
    n_weak = max(1, int(total_candidates * review_ratio))
    n_mastered = min(max(0, total_candidates - n_new - n_weak), 2)

    selected = []

    # ۱. کلمات ضعیف (اولویت بالا)
    random.shuffle(weak_words)
    selected.extend(weak_words[:n_weak])

    # ۲. کلمات جدید
    random.shuffle(new_words)
    selected.extend(new_words[:n_new])

    # ۳. کلمات ضعیف بین‌درسی
    if len(selected) < n_new + n_weak:
        remaining = (n_new + n_weak) - len(selected)
        if remaining > 0:
            try:
                exclude_list = list(exclude_ids)[:500]
                global_weak = db.words.get_weak(
                    user_id=user_id, limit=remaining * 2, exclude_ids=exclude_list
                )
                for w in global_weak:
                    wd = {
                        "id": w.id, "german": w.german, "persian": w.persian,
                        "article": w.article, "word_type": w.word_type,
                        "example_de": w.example_de, "example_fa": w.example_fa,
                        "story_suitability": 3, "story_roles": "",
                        "topics": "", "contexts": "",
                    }
                    if not any(x["id"] == w.id for x in selected):
                        selected.append(wd)
                    if len(selected) >= n_new + n_weak:
                        break
            except Exception as e:
                logger.warning("خطا در گرفتن کلمات ضعیف بین‌درسی: %s", e)

    # ۴. کلمات mastered (حداکثر ۲)
    if n_mastered > 0:
        random.shuffle(mastered_words)
        selected.extend(mastered_words[:n_mastered])

    # ۵. پر کردن اگر کم بود
    if len(selected) < MIN_STORY_WORDS:
        used_ids = {w["id"] for w in selected}
        for w in story_friendly:
            if w["id"] not in used_ids and w["id"] not in exclude_ids:
                selected.append(w)
            if len(selected) >= MIN_STORY_WORDS:
                break

    return selected[:MAX_CANDIDATE_WORDS]


# ─── انتخاب ژانر هوشمند ──────────────────────────────────────────
def _select_genre(level: str, lesson_title: str) -> Dict:
    """انتخاب ژانر بر اساس سطح و موضوع درس."""
    allowed_ids = GENRE_BY_LEVEL.get(level, ["daily"])
    allowed_genres = [g for g in GENRES if g["id"] in allowed_ids]

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
        "hotel": ["daily", "social"],
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

        if total < 10:
            return lesson_level

        levels = ["A1", "A2", "B1", "B2"]
        try:
            idx = levels.index(lesson_level)
        except ValueError:
            return lesson_level

        if accuracy < 55 and idx > 0:
            return levels[idx - 1]
        elif accuracy > 85 and idx < len(levels) - 1:
            return levels[idx + 1]

        return lesson_level
    except Exception:
        return lesson_level


# ─── مرحله ۱: برنامه‌ریزی با LLM ─────────────────────────────────
async def _plan_story(words: List[Dict], level: str, lesson_title: str) -> Optional[Dict]:
    """LLM Planning با metadata غنی."""
    if not llm.is_available():
        return None

    word_lines = []
    for w in words:
        art = (w.get("article") or "").strip()
        disp = f"{art} {w['german']}".strip() if art else w["german"]

        line = f'- "{disp}" ({w.get("persian", "")}) [{w.get("word_type", "")}]'

        # ─── اضافه کردن metadata ───
        roles = w.get("story_roles") or ""
        topics = w.get("topics") or ""
        situations = w.get("common_situations") or ""
        example = w.get("example_de") or ""

        if roles:
            line += f' roles=[{roles}]'
        if topics:
            line += f' topics=[{topics}]'
        if situations:
            line += f' situations=[{situations}]'
        if example:
            line += f' example="{example}"'

        word_lines.append(line)

    word_list = "\n".join(word_lines)

    prompt = f"""You are a German language teacher planning a SHORT story for {level} learners.

LESSON THEME: {lesson_title or "Everyday Life"}

AVAILABLE VOCABULARY (with metadata):
{word_list}

YOUR TASK:
1. Look at the topics, situations, and story_roles metadata.
2. Find a COMMON THEME or SITUATION that connects most of these words.
3. Choose a SIMPLE, natural situation (one central event).
4. From the vocabulary above, select ONLY 3-5 words that:
   - Fit NATURALLY into this situation
   - Have compatible story_roles (setting + action + person/object)
   - Share related topics or contexts
5. REJECT words that would feel forced or don't connect to the theme.
6. Suggest a small problem and a simple resolution.

Return ONLY valid JSON:
{{
    "situation_de": "Eine kurze Beschreibung der Situation auf Deutsch",
    "situation_en": "A short description in English",
    "selected_words": ["word1", "word2", "word3"],
    "rejected_words": ["word4", "word5"],
    "problem": "One small problem that happens",
    "resolution": "How the problem is simply resolved"
}}"""

    try:
        content = await llm._chat(
            "You are a German language teacher. Output ONLY valid JSON.",
            prompt,
            temperature=0.3,
            max_tokens=500,
        )
        if not content:
            return None
        result = json.loads(llm._clean_json(content))
        if not isinstance(result, dict):
            return None
        selected = result.get("selected_words", [])
        if not selected or len(selected) < 2:
            return None
        situation = result.get("situation_de", result.get("situation_en", ""))
        if not situation:
            return None
        logger.info(
            "📋 Story Plan: situation='%s', selected=%d/%d, rejected=%d",
            situation[:60], len(selected), len(words),
            len(result.get("rejected_words", [])),
        )
        return result
    except Exception as e:
        logger.warning("خطا در برنامه‌ریزی داستان: %s", e)
        return None


# ─── فیلتر کلمات بر اساس انتخاب LLM ──────────────────────────────
def _filter_words_by_plan(words: List[Dict], plan: Dict) -> List[Dict]:
    """کلمات رو بر اساس انتخاب LLM فیلتر کن."""
    selected_words = set(w.lower() for w in plan.get("selected_words", []))

    if not selected_words:
        return words[:MAX_STORY_WORDS]  # fallback

    filtered = []
    for w in words:
        german = w.get("german", "").lower()
        if german in selected_words:
            filtered.append(w)

    # اگر خیلی کم شد، fallback
    if len(filtered) < 2:
        logger.warning("فیلتر LLM خیلی سخت‌گیرانه بود، fallback")
        return words[:MAX_STORY_WORDS]

    return filtered[:MAX_STORY_WORDS]


# ─── ساخت پرامپت داستان (رویکرد طبیعی) ──────────────────────────
def _build_enhanced_prompt(
    words: List[Dict],
    level: str,
    lesson_title: str,
    genre: Dict,
    situation: str,
    problem: str = "",
    resolution: str = "",
    story_number: int = 1,
    total_stories_in_series: int = 1,
) -> str:
    """ساخت پرامپت با اولویت طبیعی بودن."""

    # ─── Core Vocabulary با metadata ───
    core_lines = []
    for w in words:
        art = (w.get("article") or "").strip()
        disp = f"{art} {w['german']}".strip() if art else w["german"]
        line = f'- "{disp}" ({w.get("persian", "")})'

        # اضافه کردن example sentence
        if w.get("example_de"):
            line += f' — example: "{w["example_de"]}"'

        # اضافه کردن collocation
        if w.get("collocation_de"):
            line += f' — collocation: "{w["collocation_de"]}"'

        core_lines.append(line)

    core_vocab = "\n".join(core_lines)

    # ─── Support Vocabulary ───
    support_vocab = """SUPPORT VOCABULARY (use freely for natural flow, do NOT force them):
gehen, kommen, haben, sein, machen, sagen, sehen, geben, nehmen, finden,
wollen, können, müssen, möchten,
heute, morgen, jetzt, hier, dort, gut, schlecht, schön, müde, hungrig,
und, aber, denn, oder."""

    # ─── گرامر ───
    grammar_style = f"""GRAMMAR & STYLE (Natural German for {level}):
- Use primarily Präsens. Modal verbs (können, müssen, wollen, möchten) are ALLOWED.
- Keep sentences short but natural. Flow matters more than strict word count.
- Simple 'weil', 'dass', 'und', 'aber', 'denn' are fine. Avoid complex nested clauses.
- NO literary or poetic language. NO Plusquamperfekt. NO Genitiv.
- The text must be 100% German. NO Persian inside the text."""

    # ─── ساختار داستان ───
    plot_structure = f"""STORY STRUCTURE (CRITICAL):
- One story = ONE central situation + ONE simple problem/goal.
- CENTRAL SITUATION: {situation}
"""
    if problem:
        plot_structure += f"- THE PROBLEM: {problem}\n"
    if resolution:
        plot_structure += f"- THE RESOLUTION: {resolution}\n"
    plot_structure += """- Every sentence must logically follow the previous one.
- Do NOT try to cover multiple unrelated topics.
- Do NOT add random facts just to use a word.

NATURALNESS RULE (MOST IMPORTANT):
- If using a target word makes the story unnatural, SKIP that word.
- Naturalness has priority over target-word coverage.
- Ask: "Would a language teacher write this story without being forced to include these words?"
- If NO, rewrite.

AVOID THESE PATTERNS:
- Lists of disconnected facts
- Random personal info irrelevant to the story
- Words used unnaturally just to include them
- Repeating the same fact twice
- Multiple unrelated topics crammed together"""

    # ─── Narrow Reading ───
    series_instruction = ""
    if total_stories_in_series > 1:
        series_instruction = f"""
NARROW READING: This is story {story_number} of {total_stories_in_series} about "{lesson_title}".
Keep the same theme but change the specific situation and characters."""

    return f"""You are an expert German language teacher and creative storyteller.
Write a SHORT, NATURAL, and ENGAGING story for {level} learners.

CENTRAL SITUATION: {situation}
LESSON THEME: {lesson_title or "Everyday Life"}
LEVEL: {level}
{series_instruction}

{grammar_style}

{plot_structure}

VOCABULARY:
These are suggested words. Use the ones that fit naturally. SKIP any that don't fit.
Do NOT force a word into the story just to include it.

SUGGESTED WORDS:
{core_vocab}

{support_vocab}

FORMATTING RULES:
- Story length: 6-10 sentences.
- Include at least 1-2 lines of direct speech („...").
- Vary your openings. Do NOT always start with "Ich bin [Name]. Ich bin [Adjektiv]."
- Do NOT just list facts. Make it a coherent narrative.

QUESTIONS: Create 3 questions IN GERMAN:
1. COMPREHENSION: About the plot (set "question_type": "comprehension", "word_id": null).
2. VOCABULARY: Meaning of a word used in the story (set "question_type": "vocabulary", "word_id": <id>).
3. DETAIL: A simple fact from the story (set "question_type": "detail", "word_id": null).

Return ONLY valid JSON:
{{
    "title_de": "Short German title",
    "title_fa": "Persian title",
    "text_de": "100% German story text, no Persian inside",
    "text_fa": "Natural Persian translation",
    "questions": [
        {{
            "question": "German question?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "exact text of correct option",
            "word_id": null,
            "question_type": "comprehension"
        }}
    ]
}}"""


# ─── اعتبارسنجی طبیعی بودن ────────────────────────────────────────
async def _validate_story_naturalness(
    text_de: str, words: List[Dict], level: str
) -> bool:
    """با LLM بررسی کن آیا داستان طبیعی است یا نه."""
    if not llm.is_available():
        return True

    word_list = ", ".join(f'"{w["german"]}"' for w in words)

    prompt = f"""You are a strict German language teacher.
Read this {level} story and answer ONE question:

"Would a language teacher write this story even WITHOUT being forced to include specific vocabulary?"

Story:
"{text_de}"

Suggested words: {word_list}

Check for:
1. Random facts that don't connect to the plot
2. Contradictory or nonsensical situations
3. Words used unnaturally just to include them
4. Multiple unrelated topics crammed together
5. Sentences that don't logically follow each other

Answer ONLY "OK" or "BAD: <short reason>"."""
    try:
        result = await llm._chat(
            "You are a strict German teacher. Output only OK or BAD.",
            prompt,
            temperature=0.1,
            max_tokens=80,
        )
        if not result:
            return True

        result = result.strip()
        if result.startswith("OK"):
            logger.info("✅ Naturalness check passed")
            return True

        logger.warning("❌ Naturalness check failed: %s", result)
        return False
    except Exception as e:
        logger.warning("خطا در naturalness check: %s", e)
        return True


# ─── تولید داستان ─────────────────────────────────────────────────
async def _generate_story_for_lesson(
    user_id: int, lesson_id: int, exclude_ids: Set[int] = None
):
    """تولید داستان پویا با Two-Step Generation."""
    exclude_ids = exclude_ids or set()

    # ─── سطح تطبیقی ───
    lesson_level = db.get_book_level_by_lesson(lesson_id) or "A1"
    level = _get_adaptive_level(user_id, lesson_level)

    # ─── مرحله ۰: انتخاب candidate pool از دیتابیس ───
    words = _select_smart_words(user_id, lesson_id, exclude_ids, level)
    if len(words) < MIN_STORY_WORDS:
        logger.warning(
            "کلمات کافی برای داستان درس %d یافت نشد (%d کلمه)",
            lesson_id, len(words),
        )
        return None

    lesson = db.get_lesson(lesson_id)
    lesson_title = lesson[1] if lesson and len(lesson) > 1 else ""

    # ─── مرحله ۱: برنامه‌ریزی با LLM ───
    plan = await _plan_story(words, level, lesson_title)

    if plan:
        words = _filter_words_by_plan(words, plan)
        situation = plan.get("situation_de", plan.get("situation_en", ""))
        problem = plan.get("problem", "")
        resolution = plan.get("resolution", "")

        logger.info(
            "📝 بعد از LLM Planning: %d کلمه انتخاب شد", len(words),
        )
    else:
        # fallback: بدون plan، مستقیم با کلمات candidate
        situation = f"Eine Geschichte über: {lesson_title or 'Alltag'}"
        problem = "Something small goes wrong."
        resolution = "The problem is simply resolved."
        words = words[:MAX_STORY_WORDS]

    # ─── Narrow Reading ───
    story_count = db.get_story_count_by_lesson(lesson_id)
    total_in_series = 3
    story_number = (story_count % total_in_series) + 1

    # ─── ژانر هوشمند ───
    genre = _select_genre(level, lesson_title)

    prompt = _build_enhanced_prompt(
        words, level, lesson_title, genre, situation,
        problem=problem,
        resolution=resolution,
        story_number=story_number,
        total_stories_in_series=total_in_series,
    )

    # ─── مرحله ۲: تولید داستان ───
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

            # ─── اعتبارسنجی ۱: عدم وجود فارسی ───
            if re.search(r"[\u0600-\u06FF]", text_de):
                text_de = re.sub(
                    r"\s*\([^)]*[\u0600-\u06FF][^)]*\)", "", text_de
                ).strip()
                if re.search(r"[\u0600-\u06FF]", text_de):
                    logger.warning("داستان شامل فارسی - تلاش %d", attempt + 1)
                    continue

            # ─── اعتبارسنجی ۲: طول منطقی ───
            word_count = len(text_de.split())
            if word_count < 30 or word_count > 250:
                logger.warning(
                    "طول داستان غیرمنطقی: %d کلمه - تلاش %d",
                    word_count, attempt + 1,
                )
                continue

            # ─── اعتبارسنجی ۳: پوشش کلمات (آستانه بالاتر) ───
            text_lower = text_de.lower()
            used = sum(1 for w in words if w["german"].lower() in text_lower)
            usage_ratio = used / len(words) if words else 0
            if usage_ratio < 0.6:  # ← تغییر از 0.4 به 0.6
                logger.warning(
                    "Coverage پایین: %d/%d (%.0f%%) - تلاش %d",
                    used, len(words), usage_ratio * 100, attempt + 1,
                )
                continue

            # ─── حذف naturalness check جداگانه ───
            # (prompt بهتر جایگزینش می‌شود)

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

                q_type = q.get("question_type", "comprehension")
                if q_type not in ("comprehension", "vocabulary", "detail"):
                    q_type = "comprehension"
                q["question_type"] = q_type

                try:
                    word_id = int(q.get("word_id"))
                except Exception:
                    word_id = None

                if q_type == "vocabulary" and word_id not in target_id_set:
                    word_id = None
                elif q_type in ("comprehension", "detail"):
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
                "✅ داستان id=%d برای درس %d (%d کلمه، %d سوال، ژانر: %s، سری: %d/%d)",
                story_id, lesson_id, len(words), len(valid_q),
                genre["fa"], story_number, total_in_series,
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
    context.user_data["story_hint_level"] = 0

    title = story.get("title_de") or story.get("title_fa") or "داستان"

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
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("💡 کمک", callback_data=f"story_hint:{story_id}")],
        [InlineKeyboardButton("🧩 کلمات", callback_data=f"story_words:{story_id}")],
        [InlineKeyboardButton("📖 داستان بعدی", callback_data=f"story_next:{story['lesson_id']}")],
        [InlineKeyboardButton("🔙 بازگشت به درس", callback_data=f"lesson_{story['lesson_id']}")],
    ])
    await render(query, msg, reply_markup=kb)


# ─── راهنمای تدریجی (Progressive Hint) ────────────────────────────
async def show_story_hint(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    hint_level = context.user_data.get("story_hint_level", 0)
    user_id = query.from_user.id

    if hint_level == 0:
        target_ids = _safe_id_list(story.get("target_word_ids"))
        words = db.get_word_objects_by_ids(target_ids) if target_ids else []

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
        title_fa = story.get("title_fa") or story.get("title_de") or "داستان"
        text_fa = story.get("text_fa") or ""

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
        await show_story_translation(query, context, story_id)


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
    story = db.get_story(story_id)
    if not story:
        try:
            await query.answer("❌ داستان پیدا نشد.", show_alert=True)
        except Exception:
            pass
        return

    title = story.get("title_de") or "داستان"
    msg = (
        f"🔊+📖 <b>همزمان بخوان و بشنو</b>\n\n"
        f"📖 <b>{esc(title)}</b>\n"
        f"{esc(story['text_de'])}\n\n"
        f"🎧 صدا در حال پخش است. همراه با متن گوش بده."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎧 حالا فقط بشنو", callback_data=f"story_listen_only:{story_id}")],
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
    ])
    await render(query, msg, reply_markup=kb)

    audio_path = await tts.get_audio_path(story["text_de"])
    if audio_path:
        try:
            with open(audio_path, "rb") as f:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id, audio=f, title=title,
                    performer="German Bot",
                    reply_to_message_id=query.message.message_id,
                    allow_sending_without_reply=True,
                )
        except Exception as e:
            logger.error("خطا در پخش صدای Listen & Read: %s", e)


# ─── Listen Only ──────────────────────────────────────────────────
async def play_story_listen_only(query, context, story_id: int):
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

    audio_path = await tts.get_audio_path(story["text_de"])
    if audio_path:
        try:
            with open(audio_path, "rb") as f:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id, audio=f,
                    title=story.get("title_de") or "داستان",
                    performer="German Bot",
                    reply_to_message_id=query.message.message_id,
                    allow_sending_without_reply=True,
                )
        except Exception as e:
            logger.error("خطا در پخش صدای Listen Only: %s", e)


# ─── پخش ساده صدا (سازگاری با route قدیمی) ───────────────────────
async def play_story_audio(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        try:
            await query.answer("❌ داستان پیدا نشد.", show_alert=True)
        except Exception:
            pass
        return

    audio_path = await tts.get_audio_path(story["text_de"])
    if not audio_path:
        try:
            await query.answer("❌ تلفظ در دسترس نیست.", show_alert=True)
        except Exception:
            pass
        return

    try:
        with open(audio_path, "rb") as f:
            await context.bot.send_audio(
                chat_id=query.message.chat_id, audio=f,
                title=story.get("title_de") or "داستان",
                performer="German Bot",
                reply_to_message_id=query.message.message_id,
                allow_sending_without_reply=True,
            )
        await query.answer("🔊 در حال پخش...")
    except Exception as e:
        logger.error("خطا در پخش صدای داستان: %s", e)
        try:
            await query.answer("❌ خطا در پخش صدا.", show_alert=True)
        except Exception:
            pass


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

    db.update_quiz_stats(user_id, is_correct)
    db.learning.record_story_answer(user_id, story_id, is_correct)

    if q_type == "comprehension":
        key = "comprehension_correct" if is_correct else "comprehension_wrong"
        quiz[key] += 1
    elif q_type == "vocabulary":
        key = "vocabulary_correct" if is_correct else "vocabulary_wrong"
        quiz[key] += 1
    elif q_type == "detail":
        key = "detail_correct" if is_correct else "detail_wrong"
        quiz[key] += 1

    # فقط Vocabulary questions روی FSRS اثر بگذارند
    if q_type == "vocabulary" and word_id:
        db.learning.record_skill(user_id, word_id, "reading", is_correct)
        from srs_service import FSRSService
        fsrs_service = FSRSService(db)
        grade = 3 if is_correct else 1
        fsrs_service.review(user_id, word_id, grade)

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

    comp_c = quiz.get("comprehension_correct", 0)
    comp_w = quiz.get("comprehension_wrong", 0)
    comp_t = comp_c + comp_w
    comp_acc = int(comp_c / comp_t * 100) if comp_t else 0

    vocab_c = quiz.get("vocabulary_correct", 0)
    vocab_w = quiz.get("vocabulary_wrong", 0)
    vocab_t = vocab_c + vocab_w
    vocab_acc = int(vocab_c / vocab_t * 100) if vocab_t else 0

    detail_c = quiz.get("detail_correct", 0)
    detail_w = quiz.get("detail_wrong", 0)
    detail_t = detail_c + detail_w
    detail_acc = int(detail_c / detail_t * 100) if detail_t else 0

    db.record_activity(query.from_user.id, 5 * correct)

    msg = (
        f"🏁 <b>کوییز داستان تمام شد!</b>\n"
        f"✅ درست: {correct}\n"
        f"❌ اشتباه: {wrong}\n"
        f"🎯 دقت کل: {accuracy:.0f}%\n\n"
    )
    if comp_t:
        msg += f"📖 درک مطلب: {comp_c}/{comp_t} ({comp_acc}%)\n"
    if detail_t:
        msg += f"🔍 جزئیات: {detail_c}/{detail_t} ({detail_acc}%)\n"
    if vocab_t:
        msg += f"🧠 واژگان: {vocab_c}/{vocab_t} ({vocab_acc}%)\n"
    msg += "\n"

    if accuracy == 100:
        msg += "🌟 عالی! داستان را کامل فهمیدی!"
    elif accuracy >= 60:
        msg += "👍 خوب بود! یک بار دیگر داستان را بخوان."
    else:
        msg += "💡 پیشنهاد: داستان را دوباره با «همزمان بخوان و بشنو» تمرین کن."

    kb_buttons = []

    if accuracy < 60:
        kb_buttons.append([
            InlineKeyboardButton("🔄 Replay با راهنمایی", callback_data=f"story_replay:{story_id}")
        ])
    else:
        kb_buttons.append([
            InlineKeyboardButton("📖 خواندن دوباره", callback_data=f"story_view:{story_id}")
        ])

    kb_buttons.append([InlineKeyboardButton("❓ کوییز دوباره", callback_data=f"story_quiz:{story_id}")])

    if lesson_id:
        kb_buttons.append([InlineKeyboardButton("📖 داستان بعدی", callback_data=f"story_next:{lesson_id}")])

    kb_buttons.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")])

    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))


# ─── Story Replay ─────────────────────────────────────────────────
async def replay_story(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

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