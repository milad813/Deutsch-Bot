#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f bot.py || ! -f database.py ]]; then
  echo "❌ لطفاً در پوشه اصلی ربات اجرا کنید."
  exit 1
fi

BACKUP_DIR=".backup_story_ondemand_$(date +%Y%m%d_%H%M%S)"
export BACKUP_DIR
echo "📦 بکاپ‌گیری در: $BACKUP_DIR"

mkdir -p "$BACKUP_DIR/handlers"
for f in database.py handlers/callback_router.py handlers/menus.py services.py handlers/story_handlers.py; do
  [[ -f "$f" ]] && cp "$f" "$BACKUP_DIR/$f" 2>/dev/null || true
done

# ============================================================
# ۱. نوشتن handlers/story_handlers.py کامل
# ============================================================
cat > handlers/story_handlers.py << 'STORYEOF'
import json
import random
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from services import db, llm, tts
from ui import esc, render, back_inline_keyboard, _short_label

logger = logging.getLogger(__name__)

STORY_WORD_TYPES = ("Noun", "Verb", "Adjective")
MAX_STORY_WORDS = 10
MIN_STORY_WORDS = 4


def _build_story_prompt(words, level, lesson_title):
    word_lines = []
    for w in words:
        art = (w.get("article") or "").strip()
        disp = f"{art} {w['german']}".strip() if art else w["german"]
        word_lines.append(f'- "{disp}" = {w["persian"]}')
    word_list = "\n".join(word_lines)

    return f"""You are a creative German short-story writer for {level} language learners.

Lesson theme: {lesson_title or "everyday life"}

Write ONE short, natural, engaging story in German (6-10 sentences) using ALL of these words:
{word_list}

CRITICAL RULES:
1. The story must have a clear character, a situation, and a small resolution (a tiny plot).
2. Use simple {level} grammar (mostly Präsens, short sentences, max 10 words per sentence).
3. Each target word must appear at least once, in a grammatically correct form (conjugated/declined as needed).
4. IMPORTANT: Right after EACH target word's FIRST appearance, add its Persian meaning in parentheses.
   Example: "Anna geht in den Supermarkt (سوپرمارکت) und kauft Brot (نان)."
5. The Persian in parentheses must be SHORT (just the meaning, not a full sentence).
6. Keep the story logical and natural despite the parentheses.
7. Do NOT use idioms or vocabulary beyond {level}.

Also create 3 reading-comprehension questions in GERMAN about the story.
Each question must have exactly 4 options (one correct). Questions should test understanding of the story, not just vocabulary.

Return ONLY valid JSON in this exact format:
{{
  "title_de": "German title",
  "title_fa": "Persian title",
  "text_de": "The story with Persian meanings in parentheses after target words",
  "text_fa": "Full natural Persian translation of the story (no parentheses)",
  "questions": [
    {{
      "question": "German question?",
      "options": ["A", "B", "C", "D"],
      "correct_answer": "the correct option text"
    }}
  ]
}}"""


async def _generate_story_for_lesson(lesson_id: int):
    """ساخت on-demand داستان برای یک درس و ذخیره در DB."""
    words_data = db.get_words_by_lesson_full(lesson_id)
    if not words_data:
        return None

    friendly = [w for w in words_data if w.get("word_type") in STORY_WORD_TYPES]
    others = [w for w in words_data if w not in friendly]
    selected = friendly[:MAX_STORY_WORDS]
    if len(selected) < MIN_STORY_WORDS:
        selected += others[:MAX_STORY_WORDS - len(selected)]
    if len(selected) < MIN_STORY_WORDS:
        return None

    level = db.get_book_level_by_lesson(lesson_id) or "A1"
    lesson = db.get_lesson(lesson_id)
    lesson_title = lesson[1] if lesson and len(lesson) > 1 else ""

    prompt = _build_story_prompt(selected, level, lesson_title)

    for attempt in range(2):
        try:
            content = await llm._chat(
                "You are a creative German language teacher. You output only valid JSON, nothing else.",
                prompt,
                temperature=0.8,
                max_tokens=1200,
            )
            if not content:
                continue

            result = json.loads(llm._clean_json(content))
            if not isinstance(result, dict):
                continue

            text_de = str(result.get("text_de") or "").strip()
            if not text_de:
                continue

            # اعتبارسنجی: حداقل ۷۰٪ کلمات استفاده شده باشند
            text_lower = text_de.lower()
            used = sum(1 for w in selected if w["german"].lower() in text_lower)
            if len(selected) > 0 and used / len(selected) < 0.7:
                logger.warning("داستان فقط %d/%d کلمه داشت (تلاش %d)", used, len(selected), attempt + 1)
                continue

            # اعتبارسنجی سوالات
            questions = result.get("questions") or []
            valid_q = [
                q for q in questions
                if isinstance(q, dict)
                and q.get("question")
                and len(q.get("options") or []) >= 2
                and q.get("correct_answer")
            ]

            target_ids = [w["id"] for w in selected]
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
            logger.info("داستان id=%d برای درس %d ساخته شد (%d کلمه، %d سوال)",
                        story_id, lesson_id, len(selected), len(valid_q))
            return db.get_story(story_id)

        except Exception as e:
            logger.warning("خطا در ساخت داستان (تلاش %d): %s", attempt + 1, e)
            continue

    return None


async def show_story_menu(query, context, lesson_id: int):
    stories = db.get_stories_by_lesson(lesson_id)

    if not stories:
        # ── ساخت on-demand ──
        if not llm.is_available():
            await render(
                query,
                "❌ قابلیت LLM فعال نیست. نمی‌توانم داستان بسازم.\n\n"
                "در <code>.env</code> کلید <code>GROQ_API_KEY</code> را تنظیم کن.",
                reply_markup=back_inline_keyboard("🔙 بازگشت", f"lesson_{lesson_id}"),
            )
            return

        try:
            await query.answer("📖 در حال ساخت داستان...", show_alert=False)
        except Exception:
            pass

        story = await _generate_story_for_lesson(lesson_id)
        if story:
            await show_story(query, context, story["id"])
        else:
            await render(
                query,
                "❌ ساخت داستان ناموفق بود. دوباره تلاش کن.",
                reply_markup=back_inline_keyboard("🔙 بازگشت", f"lesson_{lesson_id}"),
            )
        return

    if len(stories) == 1:
        await show_story(query, context, stories[0]["id"])
        return

    kb = []
    for s in stories:
        title = s.get("title_fa") or s.get("title_de") or f"داستان {s['id']}"
        kb.append([InlineKeyboardButton(
            f"📖 {_short_label(title, 60)}",
            callback_data=f"story_view:{s['id']}",
        )])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"lesson_{lesson_id}")])
    await render(
        query,
        "📖 <b>داستان‌های این درس</b>\nیک داستان انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def show_story(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    context.user_data["current_story_id"] = story_id
    title = story.get("title_de") or story.get("title_fa") or "داستان"
    msg = f"📖 <b>{esc(title)}</b>\n\n{esc(story['text_de'])}"

    target_ids = json.loads(story.get("target_word_ids") or "[]")
    words = db.get_word_objects_by_ids(target_ids) if target_ids else []
    if words:
        word_list = "، ".join(w.display_german for w in words[:10])
        msg += f"\n\n🎯 <b>کلمات:</b> {esc(word_list)}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔊 تلفظ", callback_data=f"story_audio:{story_id}")],
        [
            InlineKeyboardButton("🇮🇷 ترجمه", callback_data=f"story_fa:{story_id}"),
            InlineKeyboardButton("🧩 کلمات", callback_data=f"story_words:{story_id}"),
        ],
        [InlineKeyboardButton("❓ سوالات درک مطلب", callback_data=f"story_quiz:{story_id}")],
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
    ])
    await render(query, msg, reply_markup=kb)


async def show_story_words(query, context, story_id: int):
    story = db.get_story(story_id)
    if not story:
        await render(query, "❌ داستان پیدا نشد.", reply_markup=back_inline_keyboard())
        return

    target_ids = json.loads(story.get("target_word_ids") or "[]")
    words = db.get_word_objects_by_ids(target_ids) if target_ids else []

    if not words:
        msg = "📭 کلمه‌ای برای این داستان ثبت نشده."
    else:
        msg = f"🧩 <b>کلمات داستان ({len(words)} کلمه)</b>\n\n"
        for w in words[:15]:
            line = f"🔹 <b>{esc(w.display_german)}</b> — {esc(w.persian)}"
            if w.example_de:
                line += f"\n    📝 {esc(w.example_de)}"
            msg += line + "\n"
        if len(words) > 15:
            msg += f"\n... و {len(words) - 15} کلمه دیگر"

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

    # حذف پرانتزهای فارسی برای TTS
    import re
    clean_text = re.sub(r'\s*\([^)]*[\u0600-\u06FF][^)]*\)', '', story["text_de"]).strip()
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

    questions = json.loads(story.get("questions_json") or "[]")
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

    correct_idx = quiz.get("current_correct_index", -1)
    is_correct = (chosen == correct_idx)
    correct_answer = options[correct_idx] if 0 <= correct_idx < len(options) else "?"

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
    total = len(quiz["questions"])
    correct = quiz["correct"]
    wrong = quiz["wrong"]
    accuracy = (correct / total * 100) if total > 0 else 0

    db.record_activity(query.from_user.id, 5 * correct)

    msg = (
        f"🏁 <b>کوییز داستان تمام شد!</b>\n\n"
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

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 خواندن دوباره", callback_data=f"story_view:{story_id}")],
        [InlineKeyboardButton("❓ کوییز دوباره", callback_data=f"story_quiz:{story_id}")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="back_to_main_menu")],
    ])
    await render(query, msg, reply_markup=kb)
STORYEOF
echo "✅ handlers/story_handlers.py نوشته شد."

# ============================================================
# ۲. Patch فایل‌های موجود با Python
# ============================================================
python3 << 'PYEOF'
import re, os

applied = 0
skipped = 0
failed = 0

def patch(path, old, new, note, use_regex=False):
    global applied, skipped, failed
    if not os.path.exists(path):
        print(f"⚠️  فایل نیست: {path} — {note}")
        failed += 1
        return
    with open(path, "r", encoding="utf-8") as f:
        s = f.read()
    if new.strip() and new.strip() in s:
        print(f"⏭️  {path}: {note} — قبلاً اعمال شده.")
        skipped += 1
        return
    if use_regex:
        s2, n = re.subn(old, new, s, count=1, flags=re.S)
        if n == 0:
            print(f"⚠️  {path}: {note} — الگو پیدا نشد.")
            failed += 1
            return
        s = s2
    else:
        if old not in s:
            print(f"⚠️  {path}: {note} — الگو پیدا نشد.")
            failed += 1
            return
        s = s.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)
    print(f"✅ {path}: {note}")
    applied += 1

# ── database.py: migration های story ──
patch(
    "database.py",
    '"ALTER TABLE word_stats ADD COLUMN difficulty REAL DEFAULT 0.0",\n        ]',
    '"ALTER TABLE word_stats ADD COLUMN difficulty REAL DEFAULT 0.0",\n'
    '            "ALTER TABLE stories ADD COLUMN title_de TEXT",\n'
    '            "ALTER TABLE stories ADD COLUMN questions_json TEXT",\n'
    '            "ALTER TABLE stories ADD COLUMN level TEXT",\n'
    '        ]',
    "migration های story",
)

# ── database.py: متدهای story ──
story_methods = '''
    # ---------- Stories ----------
    def add_story(self, lesson_id, title_de, title_fa, text_de, text_fa,
                  target_word_ids, questions_json, level):
        with self._cursor(commit=True) as c:
            c.execute(
                """INSERT INTO stories
                   (lesson_id, title_de, title_fa, text_de, text_fa,
                    target_word_ids, questions_json, level)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (lesson_id, title_de, title_fa, text_de, text_fa,
                 target_word_ids, questions_json, level),
            )
            return c.lastrowid

    def get_stories_by_lesson(self, lesson_id):
        with self._cursor() as c:
            c.execute(
                """SELECT id, title_de, title_fa, text_de, text_fa,
                          target_word_ids, questions_json, level
                   FROM stories WHERE lesson_id = ? ORDER BY id""",
                (lesson_id,),
            )
            return [
                {"id": r[0], "title_de": r[1], "title_fa": r[2],
                 "text_de": r[3], "text_fa": r[4], "target_word_ids": r[5],
                 "questions_json": r[6], "level": r[7]}
                for r in c.fetchall()
            ]

    def get_story(self, story_id):
        with self._cursor() as c:
            c.execute(
                """SELECT id, lesson_id, title_de, title_fa, text_de, text_fa,
                          target_word_ids, questions_json, level
                   FROM stories WHERE id = ?""",
                (story_id,),
            )
            r = c.fetchone()
            if not r:
                return None
            return {"id": r[0], "lesson_id": r[1], "title_de": r[2],
                    "title_fa": r[3], "text_de": r[4], "text_fa": r[5],
                    "target_word_ids": r[6], "questions_json": r[7],
                    "level": r[8]}

    def get_story_count_by_lesson(self, lesson_id):
        with self._cursor() as c:
            c.execute(
                "SELECT COUNT(*) FROM stories WHERE lesson_id = ?",
                (lesson_id,),
            )
            return c.fetchone()[0]

'''

patch(
    "database.py",
    '    def backup(self, backup_dir: str = "backups") -> str:',
    story_methods + '    def backup(self, backup_dir: str = "backups") -> str:',
    "متدهای story در database",
)

# ── callback_router.py: import story_handlers ──
patch(
    "handlers/callback_router.py",
    "from handlers import grammar_handlers\n",
    "from handlers import grammar_handlers\nfrom handlers import story_handlers\n",
    "import story_handlers",
)

# ── callback_router.py: route های story ──
patch(
    "handlers/callback_router.py",
    '    ("grammar_ans:", lambda q, c, s: grammar_handlers.handle_grammar_answer(q, c, s)),\n]',
    '    ("grammar_ans:", lambda q, c, s: grammar_handlers.handle_grammar_answer(q, c, s)),\n'
    '    ("story_lesson:", lambda q, c, s: story_handlers.show_story_menu(q, c, int(s))),\n'
    '    ("story_view:", lambda q, c, s: story_handlers.show_story(q, c, int(s))),\n'
    '    ("story_fa:", lambda q, c, s: story_handlers.show_story_translation(q, c, int(s))),\n'
    '    ("story_words:", lambda q, c, s: story_handlers.show_story_words(q, c, int(s))),\n'
    '    ("story_audio:", lambda q, c, s: story_handlers.play_story_audio(q, c, int(s))),\n'
    '    ("story_quiz:", lambda q, c, s: story_handlers.start_story_quiz(q, c, int(s))),\n'
    '    ("story_ans:", lambda q, c, s: story_handlers.handle_story_answer(q, c, s)),\n'
    ']',
    "route های story",
)

# ── services.py: session keys ──
patch(
    "services.py",
    '    "fsrs_guide_shown",\n}',
    '    "fsrs_guide_shown",\n    # Story\n    "current_story_id", "story_quiz",\n}',
    "session keys داستان",
)

# ── menus.py: دکمه داستان ──
patch(
    "handlers/menus.py",
    '        [InlineKeyboardButton("🤖 کوییز", callback_data=f"quiz_from_lesson:{lesson_id}")],\n'
    '        [InlineKeyboardButton("📐 گرامر این درس", callback_data=f"grammar_lesson:{lesson_id}")],',
    '        [InlineKeyboardButton("🤖 کوییز", callback_data=f"quiz_from_lesson:{lesson_id}")],\n'
    '        [InlineKeyboardButton("📖 داستان این درس", callback_data=f"story_lesson:{lesson_id}")],\n'
    '        [InlineKeyboardButton("📐 گرامر این درس", callback_data=f"grammar_lesson:{lesson_id}")],',
    "دکمه داستان در منوی درس",
)

print(f"\n{'='*50}")
print(f"✅ اعمال شد: {applied}")
print(f"⏭️  قبلاً بود: {skipped}")
print(f"⚠️  ناموفق: {failed}")
print(f"{'='*50}")
PYEOF

# ============================================================
# ۳. بررسی syntax
# ============================================================
echo ""
echo "🔍 بررسی syntax..."
python3 -m py_compile handlers/story_handlers.py
python3 -m py_compile database.py
python3 -m py_compile handlers/callback_router.py
python3 -m py_compile handlers/menus.py
python3 -m py_compile services.py
echo "✅ همه فایل‌ها syntax درست دارند."

echo ""
echo "🎉 تمام! حالا ربات را اجرا کن: python bot.py"
echo "   وقتی روی «📖 داستان این درس» بزنی، همان لحظه ساخته می‌شود."
