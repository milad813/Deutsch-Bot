#!/usr/bin/env python3
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from database import Database

ARTICLES = ("der", "die", "das")
ARTICLE_RE = re.compile(r"^(der|die|das)\s+(.*)$", re.IGNORECASE)


def norm(value):
    if value is None:
        return None
    value = " ".join(str(value).split())
    return value or None


def main():
    # اعمال migrationهای موجود Database برای اطمینان از schema فعلی
    Database(config.DB_PATH).close()

    backup_path = config.DB_PATH + ".pre_cleanup_backup"
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # بکاپ قبل از تغییرات
    dest = sqlite3.connect(backup_path)
    conn.backup(dest)
    dest.close()

    cur = conn.cursor()

    # --------------------------------------------------
    # 1) strip article از german و normalize
    # --------------------------------------------------
    cur.execute("SELECT id, german, article FROM words")
    rows = cur.fetchall()
    updated = 0

    for word_id, german, article in rows:
        g = norm(german)
        a = norm(article)

        if a:
            a = a.lower()
            if a not in ARTICLES:
                a = None

        m = ARTICLE_RE.match(g or "")
        if m:
            extracted_article = m.group(1).lower()
            extracted_german = norm(m.group(2))
            if extracted_german:
                g = extracted_german
                if not a:
                    a = extracted_article

        if not g:
            g = german

        if g != german or a != article:
            cur.execute(
                "UPDATE words SET german = ?, article = ? WHERE id = ?",
                (g, a, word_id),
            )
            updated += 1

    # --------------------------------------------------
    # 2) dedupe words بر اساس german + book + lesson
    # --------------------------------------------------
    cur.execute("""
        SELECT german, COALESCE(book_id, -1), COALESCE(lesson_id, -1), GROUP_CONCAT(id)
        FROM words
        GROUP BY german, COALESCE(book_id, -1), COALESCE(lesson_id, -1)
        HAVING COUNT(*) > 1
    """)
    groups = cur.fetchall()
    merged_words = 0

    for german, book_key, lesson_key, ids_csv in groups:
        ids = [int(x) for x in str(ids_csv).split(",") if x.strip().isdigit()]
        if len(ids) < 2:
            continue

        keeper = min(ids)
        dups = [i for i in ids if i != keeper]

        cur.execute("SELECT article FROM words WHERE id = ?", (keeper,))
        keeper_article = cur.fetchone()[0]

        for dup_id in dups:
            cur.execute("SELECT article FROM words WHERE id = ?", (dup_id,))
            dup_row = cur.fetchone()
            if not dup_row:
                continue

            dup_article = dup_row[0]

            if not keeper_article and dup_article:
                cur.execute(
                    "UPDATE words SET article = ? WHERE id = ?",
                    (dup_article, keeper),
                )
                keeper_article = dup_article

            # --------------------------------------------------
            # انتقال/merge word_stats
            # --------------------------------------------------
            cur.execute("""
                SELECT id, user_id, correct_count, wrong_count, last_reviewed, next_review,
                       ease_factor, interval_days, srs_level, phase, stability, difficulty
                FROM word_stats
                WHERE word_id = ?
            """, (dup_id,))
            dup_stats = cur.fetchall()

            for stat in dup_stats:
                (stat_id, user_id, corr, wrong, last_rev, next_rev,
                 ease, interval, srs, phase, stab, diff) = stat

                cur.execute("""
                    SELECT id, correct_count, wrong_count, last_reviewed, next_review,
                           ease_factor, interval_days, srs_level, phase, stability, difficulty
                    FROM word_stats
                    WHERE user_id = ? AND word_id = ?
                """, (user_id, keeper))
                keeper_stat = cur.fetchone()

                if keeper_stat is None:
                    cur.execute(
                        "UPDATE word_stats SET word_id = ? WHERE id = ?",
                        (keeper, stat_id),
                    )
                else:
                    (k_id, k_corr, k_wrong, k_last, k_next,
                     k_ease, k_interval, k_srs, k_phase, k_stab, k_diff) = keeper_stat

                    new_corr = (k_corr or 0) + (corr or 0)
                    new_wrong = (k_wrong or 0) + (wrong or 0)

                    use_dup_fields = False
                    if last_rev and (not k_last or str(last_rev) > str(k_last)):
                        use_dup_fields = True

                    if use_dup_fields:
                        cur.execute("""
                            UPDATE word_stats
                            SET correct_count = ?, wrong_count = ?, last_reviewed = ?, next_review = ?,
                                ease_factor = ?, interval_days = ?, srs_level = ?, phase = ?,
                                stability = ?, difficulty = ?
                            WHERE id = ?
                        """, (
                            new_corr, new_wrong, last_rev, next_rev,
                            ease, interval, srs, phase, stab, diff, k_id
                        ))
                    else:
                        cur.execute("""
                            UPDATE word_stats
                            SET correct_count = ?, wrong_count = ?
                            WHERE id = ?
                        """, (new_corr, new_wrong, k_id))

                    cur.execute("DELETE FROM word_stats WHERE id = ?", (stat_id,))

            # جلوگیری از خطای Foreign Key در pending_reviews
            cur.execute(
                "DELETE FROM pending_reviews WHERE word_id = ? AND user_id IN (SELECT user_id FROM pending_reviews WHERE word_id = ?)",
                (dup_id, keeper),
            )
            cur.execute("UPDATE pending_reviews SET word_id = ? WHERE word_id = ?", (keeper, dup_id))

            # انتقال فیلدهای مفید در صورت خالی بودن keeper
            cur.execute(
                """
                SELECT article, example_de, example_fa, plural_form, verb_forms,
                       comparative, collocation_de, collocation_fa, english_meaning
                FROM words WHERE id = ?
                """,
                (dup_id,),
            )
            dup_fields = cur.fetchone()
            cur.execute(
                """
                SELECT article, example_de, example_fa, plural_form, verb_forms,
                       comparative, collocation_de, collocation_fa, english_meaning
                FROM words WHERE id = ?
                """,
                (keeper,),
            )
            keeper_fields = cur.fetchone()
            if dup_fields and keeper_fields:
                field_names = [
                    "article", "example_de", "example_fa", "plural_form", "verb_forms",
                    "comparative", "collocation_de", "collocation_fa", "english_meaning",
                ]
                updates = []
                params = []
                for name, keeper_value, dup_value in zip(field_names, keeper_fields, dup_fields):
                    if (keeper_value is None or str(keeper_value).strip() == "") and dup_value is not None and str(dup_value).strip() != "":
                        updates.append(f"{name} = ?")
                        params.append(dup_value)
                if updates:
                    params.append(keeper)
                    cur.execute(f"UPDATE words SET {', '.join(updates)} WHERE id = ?", params)

            cur.execute("DELETE FROM words WHERE id = ?", (dup_id,))
            merged_words += 1

    # --------------------------------------------------
    # 3) ساخت unique index واقعی
    # --------------------------------------------------
    try:
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_words_german_book_lesson
            ON words(german, COALESCE(book_id, -1), COALESCE(lesson_id, -1))
        """)
        index_msg = "✅ ایندکس یکتا ساخته/تأیید شد."
    except sqlite3.IntegrityError as e:
        index_msg = f"⚠️ ایندکس یکتا ساخته نشد؛ هنوز duplicate وجود دارد: {e}"

    conn.commit()
    conn.close()

    print("=" * 50)
    print(f"✅ کلمات به‌روزشده (strip article/normalize): {updated}")
    print(f"✅ رکوردهای word حذف/merge شده: {merged_words}")
    print(f"📦 بکاپ قبل از cleanup: {backup_path}")
    print(index_msg)
    print("=" * 50)


if __name__ == "__main__":
    main()