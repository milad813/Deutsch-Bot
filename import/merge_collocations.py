#!/usr/bin/env python3
"""الحاق collocation_de / collocation_fa به CSV اصلی.
کاربرد: python merge_collocations.py startenA1.csv collocations.csv startenA1_with_coll.csv
هر بار که یک collocations.csv جدید (درس بعدی) ساختی، دوباره اجرا کن.
"""
import csv, re, sys

def clean_german(g):
    g = (g or "").strip()
    g = re.sub(r"\s+-\S+\s*$", "", g)         # حذف پسوند جمع مثل " -se"
    g = re.sub(r"^/(der|die|das)\s+", "", g)  # حذف "/die "
    return g.strip()

def main():
    src  = sys.argv[1] if len(sys.argv) > 1 else "startenA1.csv"
    coll = sys.argv[2] if len(sys.argv) > 2 else "collocations.csv"
    out  = sys.argv[3] if len(sys.argv) > 3 else "startenA1_with_coll.csv"

    mapping = {}
    with open(coll, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    start = 1 if (rows and rows[0] and rows[0][0].strip().lower() == "german") else 0
    for r in rows[start:]:
        if not r or not r[0].strip():
            continue
        g = clean_german(r[0])
        de = r[1].strip() if len(r) > 1 else ""
        fa = r[2].strip() if len(r) > 2 else ""
        if g:
            mapping[g] = (de, fa)

    with open(src, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        for col in ("collocation_de", "collocation_fa"):
            if col not in fields:
                fields.append(col)
        data = list(reader)

    matched = 0
    for row in data:
        de, fa = mapping.get(clean_german(row.get("german", "")), ("", ""))
        row["collocation_de"] = de
        row["collocation_fa"] = fa
        if de or fa:
            matched += 1

    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(data)

    print(f"✅ {matched} ردیف collocation گرفت (از {len(mapping)} کلید).")
    print(f"✅ نوشته شد: {out}")

if __name__ == "__main__":
    main()
