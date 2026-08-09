import json
import logging
import random
import re
from typing import List, Dict, Optional, Set
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from services import db, llm, tts
from ui import _short_label, back_inline_keyboard, esc, render

logger = logging.getLogger(__name__)

# تنظیمات داستان هوشمند
STORY_WORD_TYPES = ("Noun", "Verb", "Adjective")
MAX_STORY_WORDS = 12
MIN_STORY_WORDS = 5
TARGET_NEW_RATIO = 0.5      # 50% کلمات جدید/درس فعلی
TARGET_REVIEW_RATIO = 0.3   # 30% کلمات ضعیف/مرور
TARGET_MASTERED_RATIO = 0.2 # 20% کلمات تثبیت‌شده

GENRES = [
    {"id": "daily", "de": "Alltag", "fa": "روزمره", "desc": "موقعیت‌های عادی زندگی"},
    {"id": "adventure", "de": "Abenteuer", "fa": "ماجراجویی", "desc": "سفر یا اتفاق هیجان‌انگیز"},
    {"id": "mystery", "de": "Rätsel", "fa": "معمایی", "desc": "حل یک مشکل یا معما"},
    {"id": "humor", "de": "Humor", "fa": "طنز", "desc": "اتفاق خنده‌دار یا غیرمنتظره"},
    {"id": "social", "de": "Sozial", "fa": "اجتماعی", "desc": "دیدار با دوستان یا خانواده"},
]


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


def _select_smart_words(user_id: int, lesson_id: int, exclude_ids: Set[int]) -> List[Dict]:
    """انتخاب هوشمند کلمات بر اساس وضعیت SRS و درس."""
    all_words = db.get_words_by_lesson_full(lesson_id)
    if not all_words:
        return []

    # فیلتر کلمات مناسب داستان
    story_friendly = [w for w in all_words if w.get("word_type") in STORY_WORD_TYPES]
    
    # دسته‌بندی کلمات بر اساس وضعیت یادگیری
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
        elif stats.get("phase") == "learning" or (stats.get("wrong", 0) > stats.get("correct", 0)):
            weak_words.append(w)
        else:
            mastered_words.append(w)
    
    # محاسبه تعداد مورد نیاز از هر دسته
    total_needed = min(MAX_STORY_WORDS, len(story_friendly))
    n_new = max(1, int(total_needed * TARGET_NEW_RATIO))
    n_weak = max(1, int(total_needed * TARGET_REVIEW_RATIO))
    n_mastered = max(0, total_needed - n_new - n_weak)
    
    selected = []
    
    # 1. کلمات جدید/درس فعلی
    random.shuffle(new_words)
    selected.extend(new_words[:n_new])
    
    # 2. کلمات ضعیف (از درس فعلی + درس‌های قبل)
    random.shuffle(weak_words)
    selected.extend(weak_words[:n_weak])
    
    # اگر کلمات ضعیف کم بود، از ضعیف‌های درس‌های قبل اضافه کن
    if len(selected) < n_new + n_weak:
        remaining_weak = (n_new + n_weak) - len(selected)
        if remaining_weak > 0:
            try:
                # تبدیل set به list و محدود کردن به 500 تا (محدودیت SQLite)
                exclude_list = list(exclude_ids)[:500]
                # استفاده از repository جدید که مطمئن‌تر است
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
                    # چک کنیم قبلاً اضافه نشده باشه
                    if not any(x["id"] == w.id for x in selected):
                        selected.append(wd)
                        if len(selected) >= n_new + n_weak:
                            break
            except Exception as e:
                logger.warning("خطا در گرفتن کلمات ضعیف بین‌درسی: %s", e)
    
    # 3. کلمات تثبیت‌شده (برای اعتمادبه‌نفس)
    if len(selected) < total_needed:
        remaining = total_needed - len(selected)
        random.shuffle(mastered_words)
        selected.extend(mastered_words[:remaining])
    
    # اگر هنوز کم بود، از بقیه کلمات درس پر کن
    if len(selected) < MIN_STORY_WORDS:
        used_ids = {w["id"] for w in selected}
        for w in story_friendly:
            if w["id"] not in used_ids and w["id"] not in exclude_ids:
                selected.append(w)
                if len(selected) >= MIN_STORY_WORDS:
                    break
    
    return selected[:MAX_STORY_WORDS]

def _build_enhanced_prompt(words: List[Dict], level: str, lesson_title: str, genre: Dict) -> str:
    """ساخت پرامپت پیشرفته با ساختار داستانی واقعی."""
    word_lines = []
    for w in words:
        art = (w.get("article") or "").strip()
        disp = f"{art} {w['german']}".strip() if art else w["german"]
        word_lines.append(f'- id={w["id"]} | "{disp}" = {w["persian"]}')
    word_list = "\n".join(word_lines)
    
    grammar_rules = {
        "A1": "Only Präsens. Very short sentences (max 8 words). No Nebensätze.",
        "A2": "Präsens + Perfekt. Simple Nebensätze with 'weil', 'dass'. Max 12 words/sentence.",
        "B1": "Präteritum allowed. Konjunktiv II for politeness. Compound sentences OK.",
    }
    grammar_hint = grammar_rules.get(level, grammar_rules["A1"])
    
    return f"""You are an expert German language teacher and creative storyteller.
Write a SHORT STORY for {level} learners.

LESSON THEME: {lesson_title or "General"}
GENRE: {genre['de']} ({genre['fa']}) - {genre['desc']}
LEVEL: {level}
GRAMMAR RULES: {grammar_hint}

TARGET WORDS (must ALL appear naturally):
{word_list}

STORY STRUCTURE REQUIREMENTS:
1. CHARACTER: Give the main character a name and one personality trait.
2. SETTING: Clearly establish where and when (1-2 sentences).
3. CONFLICT: Something small goes wrong or a challenge appears.
4. RESOLUTION: The problem is solved using at least ONE target word.
5. ENDING: A satisfying emotional conclusion or short dialogue.
6. DIALOGUE: Include at least 2 lines of direct speech („...“).
7. REPETITION: Each target word must appear AT LEAST TWICE in different contexts.

FORMATTING RULES:
- After EACH target word's FIRST appearance, add Persian meaning in parentheses: „Anna kauft Brot (نان)."
- Keep parentheses SHORT (one word only).
- Story length: 8-12 sentences.
- Do NOT use idioms beyond {level}.
- Text must be natural despite parentheses.

QUESTIONS: Create 3 reading comprehension questions IN GERMAN.
- Questions must test UNDERSTANDING OF THE PLOT, not just vocabulary.
- Each question has exactly 4 options (one correct).
- If a question directly tests a specific target word, set "word_id" to that word's id. Otherwise null.

Return ONLY valid JSON:
{{
  "title_de": "German title",
  "title_fa": "Persian title",
  "text_de": "Story with Persian in parentheses after first occurrence of each target word",
  "text_fa": "Natural Persian translation (no parentheses)",
  "questions": [
    {{
      "question": "German question?",
      "options": ["A", "B", "C", "D"],
      "correct_answer": "exact text of correct option",
      "word_id": 123
    }}
  ]
}}"""


async def _generate_story_for_lesson(user_id: int, lesson_id: int, exclude_ids: Set[int] = None):
    """تولید داستان پویا با کلمات هوشمند."""
    exclude_ids = exclude_ids or set()
    
    words = _select_smart_words(user_id, lesson_id, exclude_ids)
    if len(words) < MIN_STORY_WORDS:
        logger.warning("کلمات کافی برای داستان درس %d یافت نشد (%d کلمه)", lesson_id, len(words))
        return None
    
    level = db.get_book_level_by_lesson(lesson_id) or "A1"
    lesson = db.get_lesson(lesson_id)
    lesson_title = lesson[1] if lesson and len(lesson) > 1 else ""
    
    # انتخاب ژانر تصادفی
    genre = random.choice(GENRES)
    
    prompt = _build_enhanced_prompt(words, level, lesson_title, genre)
    
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
            
            # اعتبارسنجی استفاده از کلمات
            text_lower = text_de.lower()
            used = sum(1 for w in words if w["german"].lower() in text_lower)
            usage_ratio = used / len(words) if words else 0
            
            if usage_ratio < 0.6:
                logger.warning(
                    "داستان فقط %d/%d کلمه داشت (%.0f%%) - تلاش %d",
                    used, len(words), usage_ratio * 100, attempt + 1
                )
                continue
            
            # اعتبارسنجی سوالات
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
                    
                try:
                    word_id = int(q.get("word_id"))
                except Exception:
                    word_id = None
                if word_id not in target_id_set:
                    word_id = None
                q["word_id"] = word_id
                valid_q.append(q)
            
            # ذخیره داستان
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
                "✅ داستان id=%d برای درس %d ساخته شد (%d کلمه، %d سوال، ژانر: %s)",
                story_id, lesson_id, len(words), len(valid_q), genre['fa']
            )
            return db.get_story(story_id)
            
        except Exception as e:
            logger.warning("خطا در ساخت داستان (تلاش %d): %s", attempt + 1, e)
            continue
    
    return None


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
    
    # دریافت کلماتی که قبلاً در این جلسه استفاده شده‌اند
    session_stories = context.user_data.get("story_session_word_ids", [])
    exclude_ids = set(session_stories)
    
    try:
        await query.answer("📖 در حال ساخت داستان جدید...", show_alert=False)
    except Exception:
        pass
    
    story = await _generate_story_for_lesson(user_id, lesson_id, exclude_ids)
    
    if story:
        # ثبت کلمات این داستان در سشن برای جلوگیری از تکرار
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


async def show_story(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return
    
    context.user_data["current_story_id"] = story_id
    title = story.get("title_de") or story.get("title_fa") or "داستان"
    
    # نمایش کلمات هدف با وضعیت
    target_ids = _safe_id_list(story.get("target_word_ids"))
    words = db.get_word_objects_by_ids(target_ids) if target_ids else []
    
    msg = f"📖 <b>{esc(title)}</b>\n\n{esc(story['text_de'])}"
    
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
        [InlineKeyboardButton("🔊 تلفظ", callback_data=f"story_audio:{story_id}")],
        [
            InlineKeyboardButton("🇮🇷 ترجمه", callback_data=f"story_fa:{story_id}"),
            InlineKeyboardButton("🧩 کلمات", callback_data=f"story_words:{story_id}"),
        ],
        [InlineKeyboardButton("❓ سوالات درک مطلب", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("📖 داستان بعدی با کلمات جدید", callback_data=f"story_next:{story['lesson_id']}")],
        [InlineKeyboardButton("🔙 بازگشت به درس", callback_data=f"lesson_{story['lesson_id']}")],
    ])
    
    await render(query, msg, reply_markup=kb)


async def show_story_translation(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return
    
    title = story.get("title_fa") or story.get("title_de") or "داستان"
    text_fa = story.get("text_fa") or "ترجمه‌ای موجود نیست."
    
    msg = f"🇮🇷 <b>ترجمه: {esc(title)}</b>\n\n{esc(text_fa)}"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇩🇪 متن آلمانی", callback_data=f"story_view:{story_id}")],
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("📖 داستان بعدی", callback_data=f"story_next:{story['lesson_id']}")],
    ])
    
    await render(query, msg, reply_markup=kb)


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
        msg = f"🧩 <b>کلمات داستان ({len(words)} کلمه)</b>\n\n"
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
                line += f"\n📝 {esc(w.example_de)}"
            msg += line + "\n\n"
        
        if len(words) > 15:
            msg += f"... و {len(words) - 15} کلمه دیگر"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 بازگشت به داستان", callback_data=f"story_view:{story_id}")],
        [InlineKeyboardButton("❓ سوالات", callback_data=f"story_quiz:{story_id}")],
    ])
    
    await render(query, msg, reply_markup=kb)


async def play_story_audio(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        try:
            await query.answer("❌ داستان پیدا نشد.", show_alert=True)
        except Exception:
            pass
        return
    
    clean_text = re.sub(r"\s*\([^)]*[\u0600-\u06FF][^)]*\)", "", story["text_de"]).strip()
    if not clean_text:
        clean_text = story["text_de"]
    
    audio_path = await tts.get_audio_path(clean_text)
    if not audio_path:
        try:
            await query.answer("❌ تلفظ در دسترس نیست.", show_alert=True)
        except Exception:
            pass
        return
    
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
        await query.answer("🔊 در حال پخش...")
    except Exception as e:
        logger.error("خطا در پخش صدای داستان: %s", e)
        try:
            await query.answer("❌ خطا در پخش صدا.", show_alert=True)
        except Exception:
            pass


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
    
    context.user_data["story_quiz"] = {
        "story_id": story_id,
        "questions": questions,
        "current": 0,
        "correct": 0,
        "wrong": 0,
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
    msg = f"❓ <b>سوال {num} از {total}</b>\n\n{esc(q['question'])}"
    
    kb = []
    for i, opt in enumerate(options):
        label = f"{chr(65 + i)}) {opt}"
        kb.append([InlineKeyboardButton(_short_label(label, 64), callback_data=f"story_ans:{i}")])
    
    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb))


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
    
    # 1. آپدیت آمار کلی
    db.update_quiz_stats(user_id, is_correct)
    
    # 2. آپدیت پیشرفت داستان
    db.learning.record_story_answer(user_id, story_id, is_correct)
    
    # 3. اگر سوال مربوط به کلمه خاصی هست، آپدیت skill + SRS
    if word_id:
        db.learning.record_skill(user_id, word_id, "reading", is_correct)
        # اثرگذاری روی SRS: جواب درست = مرور موفق
        from srs_service import FSRSService
        fsrs = FSRSService(db)
        grade = 3 if is_correct else 1
        fsrs.review(user_id, word_id, grade)
    
    # 4. ثبت اشتباه
    if not is_correct:
        db.learning.record_mistake(
            user_id=user_id,
            word_id=word_id,
            story_id=story_id,
            skill_type="reading" if word_id else "story",
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
    
    db.record_activity(query.from_user.id, 5 * correct)
    
    msg = (
        f"🏁 <b>کوییز داستان تمام شد!</b>\n"
        f"✅ درست: {correct}\n"
        f"❌ اشتباه: {wrong}\n"
        f"🎯 دقت: {accuracy:.0f}%\n\n"
    )
    
    if accuracy == 100:
        msg += "🌟 عالی! داستان را کامل فهمیدی!"
    elif accuracy >= 60:
        msg += "👍 خوب بود! یک بار دیگر داستان را بخوان."
    else:
        msg += "💡 پیشنهاد: داستان را دوباره بخوان و بعد دوباره تست بزن."
    
    kb_buttons = [
        [InlineKeyboardButton("📖 خواندن دوباره", callback_data=f"story_view:{story_id}")],
        [InlineKeyboardButton("❓ کوییز دوباره", callback_data=f"story_quiz:{story_id}")],
    ]
    
    if lesson_id:
        kb_buttons.append([InlineKeyboardButton("📖 داستان بعدی با کلمات جدید", callback_data=f"story_next:{lesson_id}")])
    
    kb_buttons.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")])
    
    await render(query, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))