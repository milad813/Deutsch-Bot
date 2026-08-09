#!/usr/bin/env python3
"""تولید collocation برای کلماتی که هنوز ندارند. قابل resume.
استفاده: python import/generate_collocations.py"""

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
BATCH = 8


def build_prompt(words, level):
    lines = []
    for w in words:
        art = (w.get("article") or "").strip()
        disp = f"{art} {w['german']}".strip() if art else w["german"]
        lines.append(
            f"{w['id']} | {disp} | {w['persian']} | {w.get('word_type') or ''}"
        )
    body = "\n".join(lines)
    return f"""You are a German language expert. For EACH German word below, give ONE common natural collocation or typical phrase a learner should memorize as a chunk.
Examples: "Entscheidung" -> "eine Entscheidung treffen"; "warten" -> "auf etwas warten"; "Angst" -> "Angst vor etwas haben"; "Interesse" -> "Interesse an etwas haben"; "Hunger" -> "Hunger haben".
Use the correct preposition and case. Keep it at level {level}. For function words (conjunctions, pronouns, determiners) or words with no meaningful collocation, return empty strings for both fields.

Return ONLY a JSON array, in the SAME order and SAME length as the input:
[{{"id": <id>, "collocation_de": "...", "collocation_fa": "..."}}]

WORDS:
{body}"""


async def process_batch(llm, words, level):
    prompt = build_prompt(words, level)
    try:
        content = await llm._chat(
            "You output only valid JSON arrays, nothing else.",
            prompt,
            temperature=0.3,
            max_tokens=700,
        )
        data = json.loads(llm._clean_json(content))
        if not isinstance(data, list):
            return {}, [], False

        out = {}
        empty_ids = []
        by_id = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            wid = item.get("id")
            if wid is None:
                continue
            try:
                by_id[int(wid)] = item
            except Exception:
                continue

        for w in words:
            item = by_id.get(int(w["id"]))
            if item is None:
                continue
            de = str(item.get("collocation_de") or "").strip()
            fa = str(item.get("collocation_fa") or "").strip()
            if de:
                out[int(w["id"])] = (de, fa)
            else:
                empty_ids.append(int(w["id"]))
        return out, empty_ids, True
    except Exception as e:
        logger.warning("خطا در batch collocation: %s", e)
        return {}, [], False


async def main():
    db = Database(config.DB_PATH)
    llm = LLMService(db=db)
    if not llm.is_available():
        print("❌ LLM در دسترس نیست. GROQ_API_KEY را چک کن.")
        db.close()
        return
    level = "A1"
    total = 0
    skipped_empty = 0
    no_progress_rounds = 0

    while True:
        words = db.get_words_without_collocation(limit=200)
        if not words:
            break

        progress_in_round = 0
        for i in range(0, len(words), BATCH):
            chunk = words[i : i + BATCH]
            result, empty_ids, ok = await process_batch(llm, chunk, level)
            if not ok:
                continue

            for w in chunk:
                if w["id"] in result:
                    de, fa = result[w["id"]]
                    db.update_collocation(w["id"], de, fa)
                    total += 1
                    progress_in_round += 1

            for wid in empty_ids:
                db.update_collocation(wid, "—", "")
                skipped_empty += 1
                progress_in_round += 1

            print(
                f"  این دور: {min(i + BATCH, len(words))}/{len(words)} | مجموع نوشته‌شده: {total} | بدون collocation ثبت‌شده: {skipped_empty}"
            )

        if progress_in_round == 0:
            no_progress_rounds += 1
            if no_progress_rounds >= 3:
                print(
                    "⚠️ سه دور متوالی پیشرفتی نبود؛ برای جلوگیری از حلقه بی‌پایان متوقف شد."
                )
                break
        else:
            no_progress_rounds = 0

    print(
        f"✅ تمام. {total} collocation نوشته شد. {skipped_empty} کلمه بدون collocation معتبر علامت‌گذاری شد."
    )
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
