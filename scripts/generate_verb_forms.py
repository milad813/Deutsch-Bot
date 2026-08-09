#!/usr/bin/env python3
"""تولید verb_forms برای فعل‌ها با Groq + تأیید چشمی.
استفاده: python import/generate_verb_forms.py
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from database import Database
from llm_service import LLMService

config.setup_logging()
logger = logging.getLogger(__name__)

BATCH = 10


async def main():
    db = Database(config.DB_PATH)
    llm = LLMService(db=db)

    if not llm.is_available():
        print("❌ LLM در دسترس نیست. GROQ_API_KEY را چک کن.")
        db.close()
        return

    # پیدا کردن فعل‌های بدون verb_forms
    with db._cursor() as c:
        c.execute("""
            SELECT id, german FROM words
            WHERE word_type = 'Verb'
            AND (verb_forms IS NULL OR verb_forms = '')
            ORDER BY id
        """)
        verbs = [{"id": r[0], "german": r[1]} for r in c.fetchall()]

    if not verbs:
        print("✅ همه فعل‌ها verb_forms دارند!")
        db.close()
        return

    print(f"📝 {len(verbs)} فعل بدون verb_forms پیدا شد.")
    print("=" * 60)

    approved = 0
    rejected = 0

    for i in range(0, len(verbs), BATCH):
        batch = verbs[i : i + BATCH]
        results = await llm.generate_verb_forms_batch(batch)

        if not results:
            print(f"⚠️ Batch {i // BATCH + 1}: LLM پاسخی نداد.")
            continue

        for r in results:
            if not r["verb_forms"]:
                continue
            print(f"\n🏃 {r['german']}")
            print(f"   پیشنهاد: {r['verb_forms']}")
            answer = input("   تأیید؟ (y/n/s=skip): ").strip().lower()
            if answer == "y":
                with db._cursor(commit=True) as c:
                    c.execute(
                        "UPDATE words SET verb_forms = ? WHERE id = ?",
                        (r["verb_forms"], r["id"]),
                    )
                approved += 1
                print("   ✅ ذخیره شد.")
            elif answer == "n":
                custom = input("   فرم صحیح را وارد کن (خالی = رد): ").strip()
                if custom:
                    with db._cursor(commit=True) as c:
                        c.execute(
                            "UPDATE words SET verb_forms = ? WHERE id = ?",
                            (custom, r["id"]),
                        )
                    approved += 1
                    print("   ✅ ذخیره شد (دستی).")
                else:
                    rejected += 1
                    print("   ❌ رد شد.")
            else:
                print("   ⏭️ رد شد.")
                rejected += 1

    print("\n" + "=" * 60)
    print(f"✅ تأییدشده: {approved}")
    print(f"❌ ردشده: {rejected}")
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
