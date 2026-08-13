#!/usr/bin/env python3
"""وارد کردن Grammer.json به جدول grammar_points.
استفاده: python import_grammar.py [path/to/Grammer.json]"""

import json
import os
import sys
from json import JSONDecoder

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from database import Database


def normalize(v):
    if isinstance(v, dict):
        return {k.strip(): normalize(val) for k, val in v.items()}
    if isinstance(v, list):
        return [normalize(x) for x in v]
    if isinstance(v, str):
        return v.strip()
    return v


def parse_roots(text):
    decoder = JSONDecoder()
    roots, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        obj, end = decoder.raw_decode(text, i)
        roots.append(obj)
        i = end
    lessons = []
    for r in roots:
        if isinstance(r, list):
            lessons.extend(r)
        elif isinstance(r, dict):
            lessons.append(r)
    return [normalize(x) for x in lessons]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "Grammer.json"
    if not os.path.isfile(path):
        print(f"خطا: فایل '{path}' پیدا نشد.")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    lessons = parse_roots(text)
    if not lessons:
        print("هیچ درسی در فایل پیدا نشد.")
        return

    db = Database(config.DB_PATH)
    import argparse

    parser = argparse.ArgumentParser(description="وارد کردن گرامر")
    parser.add_argument("json_path", nargs="?", default="Grammer.json")
    parser.add_argument("--book-id", type=int, help="ID کتاب مقصد")
    parser.add_argument("--book-name", type=str, help="نام کتاب مقصد")
    args = parser.parse_args()

    path = args.json_path
    # ...

    books = db.books.get_all()
    if not books:
        print("⚠️ هیچ کتابی در دیتابیس نیست. اول import_csv.py را اجرا کن.")
        sys.exit(1)

    # ✅ انتخاب کتاب
    if args.book_id:
        book_id = args.book_id
        if not db.books.get_by_id(book_id):
            print(f"❌ کتاب با ID={book_id} پیدا نشد.")
            sys.exit(1)
    elif args.book_name:
        found = [b for b in books if b[1] == args.book_name]
        if not found:
            print(f"❌ کتاب '{args.book_name}' پیدا نشد. کتاب‌های موجود:")
            for b in books:
                print(f"   ID={b[0]}: {b[1]} ({b[2]})")
            sys.exit(1)
        book_id = found[0][0]
    elif len(books) == 1:
        book_id = books[0][0]
        print(f"ℹ️ فقط یک کتاب وجود دارد: {books[0][1]}")
    else:
        print("⚠️ چند کتاب وجود دارد. لطفاً با --book-id یا --book-name مشخص کن:")
        for b in books:
            print(f"   ID={b[0]}: {b[1]} ({b[2]})")
        sys.exit(1)

    total_points = 0
    for lesson in lessons:
        ln = lesson.get("lesson_number")
        if ln is None:
            continue
        try:
            ln = int(ln)
        except Exception:
            continue
        lesson_id = db.lessons.create(book_id, ln, None)
        points = lesson.get("grammar_points", []) or []
        for p in points:
            topic_key = p.get("topic_key")
            if not topic_key:
                continue
            db.grammar.upsert(
                lesson_id=lesson_id,
                topic_key=topic_key,
                title_fa=p.get("title_fa", ""),
                level=p.get("level", ""),
                explanation_fa=p.get("explanation_fa", ""),
                rule_de=p.get("rule_de", ""),
                examples_json=json.dumps(
                    p.get("examples", []) or [], ensure_ascii=False
                ),
                exercises_json=json.dumps(
                    p.get("exercises", []) or [], ensure_ascii=False
                ),
                certainty=p.get("certainty", ""),
                note=p.get("note", ""),
            )
            total_points += 1

    print("=" * 50)
    print(f"✅ درس‌های پردازش‌شده: {len(lessons)}")
    print(f"✅ نکته‌های گرامری واردشده: {total_points}")
    print("=" * 50)
    db.close()


if __name__ == "__main__":
    main()
