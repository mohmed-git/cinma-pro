#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
استبعاد مؤقت لأفلام ArabSeed الأقدم من سنة معيّنة — لتجاوز حدّ Cloudflare Pages
(20,000 ملف في النشرة الواحدة) أثناء مرحلة التجربة.

- يشيل فقط الأعمال المعلّمة arsd_source=True التي سنتها < MIN_YEAR (أو بدون سنة).
- لا يلمس الأعمال القديمة (الموقع الأصلي) ولا المسلسلات/الأنمي.
- لا يلمس السيرفرات المضافة لأفلام موجودة (تلك ليست arsd_source).
- بعد نجاح التجربة: أعد تشغيل scripts/merge_arsd_films.py من الـ CSV لإرجاع الكل،
  أو شغّل هذا السكربت بسنة أقدم (مثلاً 1900) لإبقاء الجميع.

الاستخدام:
    python3 scripts/prune_arsd_by_year.py [MIN_YEAR]
مثال (الافتراضي 2019):
    python3 scripts/prune_arsd_by_year.py 2019
"""
import ijson
import json
import os
import sys

SRC = 'src/data/generated/all.json'
TMP = SRC + '.tmp'

MIN_YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2019


def year_of(w):
    y = w.get('year')
    try:
        return int(str(y)[:4])
    except (TypeError, ValueError):
        return None


def main():
    kept = 0
    removed = 0
    kept_arsd = 0
    with open(SRC, 'rb') as fin, open(TMP, 'w', encoding='utf-8') as fout:
        fout.write('[')
        first = True
        for w in ijson.items(fin, 'item', use_float=True):
            drop = False
            if w.get('arsd_source'):
                y = year_of(w)
                if y is None or y < MIN_YEAR:
                    drop = True
                else:
                    kept_arsd += 1
            if drop:
                removed += 1
                continue
            kept += 1
            if not first:
                fout.write(',')
            first = False
            fout.write(json.dumps(w, ensure_ascii=False))
        fout.write(']')
    os.replace(TMP, SRC)
    print(f'[prune] MIN_YEAR={MIN_YEAR}')
    print(f'[prune] أعمال مُبقاة: {kept}  (منها أفلام ArabSeed: {kept_arsd})')
    print(f'[prune] أفلام ArabSeed مُستبعدة مؤقتاً: {removed}')


if __name__ == '__main__':
    main()
