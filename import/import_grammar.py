#!/usr/bin/env python3
"""وارد کردن Grammer.json به جدول grammar_points.
استفاده: python import_grammar.py [path/to/Grammer.json]"""
import os
import sys
import json
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
    books = db.get_all_books()
    if not books:
        print("⚠️ هیچ کتابی در دیتابیس نیست. اول import_csv.py را اجرا کن.")
        sys.exit(1)
    book_id = books[0][0]  # تنها کتاب: Starten Wir

    total_points = 0
    for lesson in lessons:
        ln = lesson.get("lesson_number")
        if ln is None:
            continue
        try:
            ln = int(ln)
        except Exception:
            continue
        lesson_id = db.add_lesson(book_id, ln, None)
        points = lesson.get("grammar_points", []) or []
        for p in points:
            topic_key = p.get("topic_key")
            if not topic_key:
                continue
            db.add_grammar_point(
                lesson_id=lesson_id,
                topic_key=topic_key,
                title_fa=p.get("title_fa", ""),
                level=p.get("level", ""),
                explanation_fa=p.get("explanation_fa", ""),
                rule_de=p.get("rule_de", ""),
                examples_json=json.dumps(p.get("examples", []) or [], ensure_ascii=False),
                exercises_json=json.dumps(p.get("exercises", []) or [], ensure_ascii=False),
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