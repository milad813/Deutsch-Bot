#!/usr/bin/env python3
"""تولید داستان برای هر درس با LLM.

استفاده:
  python import/generate_stories.py              # همه درس‌ها
  python import/generate_stories.py --lesson 3   # فقط درس ۳
  python import/generate_stories.py --words 12   # تعداد کلمات هر داستان
  python import/generate_stories.py --force      # حتی اگر داستان دارد، دوباره بساز
"""

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from database import Database
from llm_service import LLMService

config.setup_logging()
logger = logging.getLogger(__name__)

STORY_WORD_TYPES = ("Noun", "Verb", "Adjective")


def get_lesson_words(db, lesson_id, max_words):
    rows = db.words.fetch_all(
        """SELECT id, article, german, persian, word_type
        FROM words
        WHERE lesson_id = ? AND word_type IN ('Noun', 'Verb', 'Adjective')
        ORDER BY CASE word_type
            WHEN 'Noun' THEN 1 WHEN 'Verb' THEN 2
            WHEN 'Adjective' THEN 3 ELSE 4 END, german
        LIMIT ?""",
        (lesson_id, max_words),
    )
    words = []
    for word_id, article, german, persian, word_type in rows:
        disp = f"{article} {german}".strip() if article else german
        words.append(
            {
                "id": word_id,
                "display": disp,
                "german": german,
                "persian": persian,
                "word_type": word_type,
            }
        )
    return words


def build_prompt(words, level, lesson_title):
    word_lines = []
    for w in words:
        word_lines.append(f'- "{w["display"]}" = {w["persian"]}')
    word_list = "\n".join(word_lines)

    return f"""You are a creative German short-story writer for {level} language learners.

Lesson theme: {lesson_title or "everyday life"}

Write ONE short, natural, engaging story in German (6-10 sentences) using ALL of these words:
{word_list}

CRITICAL RULES:
1. The story must have a clear character, a situation, and a small resolution (a tiny plot).
2. Use simple {level} grammar (mostly Präsens, short sentences, max 10 words per sentence).
3. Each target word must appear at least once, in a grammatically correct form (conjugated/declined as needed).
4. The story text must be 100% German. Do NOT add any Persian translations inside the story.
5. The text_fa field will contain the full Persian translation separately.
6. Keep the story logical and natural.
7. Do NOT use idioms or vocabulary beyond {level}.

Also create 3 reading-comprehension questions in GERMAN about the story.
Each question must have exactly 4 options (one correct). Questions should test understanding of the story, not just vocabulary.

Return ONLY valid JSON in this exact format:
{{
  "title_de": "German title",
  "title_fa": "Persian title",
  "text_de": "The story in 100% German, NO Persian inside",
  "text_fa": "Full natural Persian translation of the story (no parentheses)",
  "questions": [
    {{
      "question": "German question?",
      "options": ["A", "B", "C", "D"],
      "correct_answer": "the correct option text"
    }}
  ]
}}"""


def validate_story(result, words):
    if not isinstance(result, dict):
        return False, "خروجی JSON معتبر نیست"

    text_de = str(result.get("text_de") or "").strip()
    if not text_de:
        return False, "متن داستان خالی است"

    text_lower = text_de.lower()
    used = 0
    missing = []
    for w in words:
        if w["german"].lower() in text_lower:
            used += 1
        else:
            missing.append(w["display"])

    usage_ratio = used / len(words) if words else 0
    if usage_ratio < 0.7:
        return (
            False,
            f"فقط {used}/{len(words)} کلمه استفاده شده: {', '.join(missing[:5])}",
        )

    questions = result.get("questions") or []
    valid_q = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        if not q.get("question"):
            continue
        opts = q.get("options") or []
        correct = q.get("correct_answer")
        if len(opts) >= 2 and correct:
            valid_q.append(q)

    result["questions"] = valid_q
    return True, "ok"


async def generate_story_for_lesson(llm, db, lesson_id, level, lesson_title, max_words):
    words = get_lesson_words(db, lesson_id, max_words)
    if len(words) < 4:
        print(f"  ⚠️ کلمات story-friendly کافی نیست ({len(words)} کلمه). رد شد.")
        return False

    prompt = build_prompt(words, level, lesson_title)

    for attempt in range(2):
        try:
            content = await llm._chat(
                "You are a creative German language teacher. You output only valid JSON, nothing else.",
                prompt,
                temperature=0.8,
                max_tokens=1200,
            )
            if not content:
                print(f"  ⚠️ LLM پاسخی نداد (تلاش {attempt + 1}).")
                continue

            result = json.loads(llm._clean_json(content))
            ok, msg = validate_story(result, words)
            if not ok:
                print(f"  ⚠️ اعتبارسنجی ناموفق (تلاش {attempt + 1}): {msg}")
                continue

            target_ids = [w["id"] for w in words]
            questions_json = json.dumps(result.get("questions", []), ensure_ascii=False)
            story_id = db.stories.add(
                lesson_id=lesson_id,
                title_de=str(result.get("title_de") or "").strip(),
                title_fa=str(result.get("title_fa") or "").strip(),
                text_de=str(result.get("text_de") or "").strip(),
                text_fa=str(result.get("text_fa") or "").strip(),
                target_word_ids=json.dumps(target_ids),
                questions_json=questions_json,
                level=level,
            )
            n_questions = len(result.get("questions", []))
            print(
                f"  ✅ داستان ذخیره شد (id={story_id}, {len(words)} کلمه, {n_questions} سوال)"
            )
            return True

        except json.JSONDecodeError as e:
            print(f"  ⚠️ خطای JSON (تلاش {attempt + 1}): {e}")
        except Exception as e:
            print(f"  ⚠️ خطا (تلاش {attempt + 1}): {e}")

    return False


async def main():
    parser = argparse.ArgumentParser(description="تولید داستان برای درس‌ها")
    parser.add_argument("--lesson", type=int, help="فقط این درس")
    parser.add_argument(
        "--words", type=int, default=10, help="حداکثر کلمات هر داستان (پیش‌فرض ۱۰)"
    )
    parser.add_argument(
        "--force", action="store_true", help="حتی اگر درس داستان دارد، دوباره بساز"
    )
    args = parser.parse_args()

    db = Database(config.DB_PATH)
    llm = LLMService(db=db)

    if not llm.is_available():
        print("❌ LLM در دسترس نیست. GROQ_API_KEY را چک کن.")
        db.close()
        return

    if args.lesson:
        lesson_info = db.lessons.get_by_id(args.lesson)
        if not lesson_info:
            print(f"❌ درس {args.lesson} پیدا نشد.")
            db.close()
            return
        level = db.books.get_level_by_lesson(args.lesson) or "A1"
        title = lesson_info[2] or ""
        print(f"📖 درس {args.lesson} ({title or level})...")
        await generate_story_for_lesson(llm, db, args.lesson, level, title, args.words)
    else:
        total = 0
        for book_id, book_name, level in db.books.get_all():
            lessons = db.lessons.get_by_book(book_id)
            print(f"\n📚 {book_name} ({level})")
            for lid, lnum, ltitle in lessons:
                if not args.force and db.stories.get_count(lid) > 0:
                    print(f"  ⏭️ درس {lnum}: قبلاً داستان دارد.")
                    continue
                print(f"  📖 درس {lnum}: {ltitle or ''}...")
                ok = await generate_story_for_lesson(
                    llm, db, lid, level or "A1", ltitle or "", args.words
                )
                if ok:
                    total += 1
        print(f"\n✅ {total} داستان جدید ساخته شد.")

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
