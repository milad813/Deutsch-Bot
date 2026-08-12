#!/usr/bin/env python3
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from database import Database

ARTICLES = ("der", "die", "das")


def _parse_int(value, default=None):
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def norm(value):
    if value is None:
        return None
    value = " ".join(str(value).split())
    return value or None


def pick(row, *keys):
    for key in keys:
        value = norm(row.get(key))
        if value is not None:
            return value
    return None


def clean_article(value, german=None):
    for source in (value, german):
        if not source:
            continue
        match = re.search(r"\b(der|die|das)\b", str(source).lower())
        if match:
            return match.group(1)
    return None


WORD_TYPES = (
    "Noun",
    "Verb",
    "Adjective",
    "Adverb",
    "Preposition",
    "Pronoun",
    "Conjunction",
    "Phrase",
)


def clean_word_type(value):
    value = norm(value)
    if not value:
        return None

    lowered = value.lower()
    for t in WORD_TYPES:
        if t.lower() in lowered:
            return t

    return value.capitalize()


def split_german_article(german, article=None):
    german = norm(german) or ""
    match = re.match(r"^(der|die|das)\s+(.*)$", german, re.IGNORECASE)
    if match:
        extracted_article = match.group(1).lower()
        extracted_german = match.group(2).strip()
        return extracted_german, article or extracted_article
    return german, article


def main():
    if len(sys.argv) < 2:
        print("استفاده: python import_csv.py <path_to_csv_file>")
        print("مثال: python import_csv.py Starten_Wir.csv")
        sys.exit(1)

    csv_file = sys.argv[1]
    if not os.path.isfile(csv_file):
        print(f"خطا: فایل '{csv_file}' وجود ندارد.")
        sys.exit(1)

    db = Database(config.DB_PATH)

    try:
        with open(csv_file, "r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

        if not rows:
            print("هیچ کلمه‌ای در فایل CSV یافت نشد.")
            return

        book_cache = {}
        lesson_cache = {}
        imported = 0
        skipped = 0

        for row in rows:
            book_name = pick(row, "book_name") or "Unknown"
            level = pick(row, "level") or "A1"

            lesson_number = norm(row.get("lesson_number"))
            try:
                lesson_number = int(lesson_number)
            except Exception:
                lesson_number = None

            german = pick(row, "german")
            persian = pick(row, "persian")

            if not german or not persian or lesson_number is None:
                skipped += 1
                continue

            book_key = (book_name, level)
            if book_key not in book_cache:
                book_cache[book_key] = db.add_book(book_name, level)
            book_id = book_cache[book_key]

            lesson_key = (book_id, lesson_number)
            if lesson_key not in lesson_cache:
                lesson_title = pick(row, "lesson_title") or f"درس {lesson_number}"
                lesson_id = db.add_lesson(book_id, lesson_number, lesson_title)
                db.set_lesson_title_if_empty(lesson_id, lesson_title)
                lesson_cache[lesson_key] = lesson_id
            lesson_id = lesson_cache[lesson_key]

            article = clean_article(pick(row, "article"), german)
            german, article = split_german_article(german, article)

            if not german:
                skipped += 1
                continue

            word_type = clean_word_type(pick(row, "word_type"))

            db.upsert_word(
                german_word=german,
                persian_meaning=persian,
                book_id=book_id,
                lesson_id=lesson_id,
                article=article,
                english_meaning=pick(row, "english_meaning", "english"),
                word_type=word_type,
                plural_form=pick(row, "plural_form", "plural"),
                verb_forms=pick(row, "verb_forms"),
                comparative=pick(row, "comparative"),
                example_de=pick(row, "example_de"),
                example_fa=pick(row, "example_fa"),
                collocation_de=pick(row, "collocation_de"),
                collocation_fa=pick(row, "collocation_fa"),
                # ─── فیلدهای جدید CSV ───
                cefr_estimated=pick(row, "cefr_estimated"),
                topics=pick(row, "topics"),
                contexts=pick(row, "contexts"),
                common_situations=pick(row, "common_situations"),
                story_roles=pick(row, "story_roles"),
                related_words=pick(row, "related_words"),
                common_collocations_de=pick(row, "common_collocations_de"),
                story_suitability=_parse_int(pick(row, "story_suitability"), default=3),
                story_suitability_reason=pick(row, "story_suitability_reason"),
            )

            imported += 1

        print("\n" + "=" * 50)
        print(f"✅ تعداد کلمات ایمپورت‌شده: {imported}")
        print(f"⚠️ تعداد کلمات ردشده: {skipped}")
        print(f"📚 تعداد کتاب‌ها: {len(book_cache)}")
        print(f"📖 تعداد درس‌های دیده‌شده: {len(lesson_cache)}")
        print(f"📦 تعداد کل کلمات دیتابیس: {db.get_word_count()}")
        print("=" * 50)

    except Exception as e:
        print(f"❌ خطای غیرمنتظره: {e}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
