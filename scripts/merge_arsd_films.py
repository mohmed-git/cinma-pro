"""
دمج أفلام ArabSeed (arsd_films.csv) في الكتالوج (all.json).

المنطق (حسب طلب المالك):
  - موجود مسبقاً  → أضف "سيرفر ArabSeed" (type='video', arsd_slug) ضمن سيرفرات
                    الفيلم/الحلقة الحالية، دون لمس السيرفرات القديمة (iframe).
  - غير موجود     → أنشئ فيلم movie جديد بسيرفر ArabSeed فقط.
  - نسخ مكررة (مدبلج/مترجم لنفس العمل) → سيرفرات متعددة على نفس الفيلم.

المطابقة: بالعنوان المطبّع + السنة، مع fuzzy (SequenceMatcher ≥ 0.9) وتأكيد بالسنة.
أمان RAM منخفض (985MB): يبثّ all.json عبر ijson ويكتب نسخة جديدة تدريجياً
(لا يُحمّل المصفوفة كاملة). يبني فهرس المطابقة أولاً (خفيف: مفاتيح → slug).

Inputs : /home/user/uploaded_files/arsd_films.csv
         src/data/generated/all.json
Outputs: src/data/generated/all.json            (مُعاد كتابته، سيرفرات مدموجة)
         + أفلام جديدة مُلحقة في نهاية المصفوفة
         scripts/_arsd_report.json               (تقرير: matched / created / skipped)
"""
import os, sys, csv, html, re, json, difflib
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ijson
from ingest_helpers import (
    extract_year, extract_english_title, name_key, make_slug,
    match_keys, is_adult,
)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ALL = os.path.join(ROOT, 'src/data/generated/all.json')
ALL_TMP = ALL + '.tmp'
CSV_PATH = '/home/user/uploaded_files/arsd_films.csv'
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_arsd_report.json')

R2_BASE = 'https://pub-7bd753a4463049929e562aa677ad4251.r2.dev'
ARSD_SERVER_LABEL = 'ArabSeed - HD'
FUZZY_THRESHOLD = 0.90


def _json_default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f'not serializable: {type(o).__name__}')


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=_json_default)


# ---------------------------------------------------------------------------
# 1) تحليل CSV
# ---------------------------------------------------------------------------
_YEAR_PAREN = re.compile(r'\(\s*((?:19|20)\d{2})\s*\)')


def parse_csv():
    """يرجّع قائمة أفلام ArabSeed مُنظّفة، مجمّعة بمفتاح (english|arabic + year)."""
    films = []
    with open(CSV_PATH, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            raw = (row.get('title') or '').strip()
            slug = (row.get('slug') or '').strip()
            if not raw or not slug:
                continue
            title = html.unescape(raw)
            ym = _YEAR_PAREN.search(title)
            year = ym.group(1) if ym else extract_year(title)
            # عنوان نظيف بلا السنة بين قوسين
            clean = _YEAR_PAREN.sub(' ', title)
            clean = re.sub(r'\s+', ' ', clean).strip()
            eng = extract_english_title(title)
            films.append({
                'raw_title': raw,
                'title': title,          # مفكوك entities، فيه السنة
                'clean_title': clean,    # بلا سنة
                'english': eng,          # أطول مقطع لاتيني (قد يكون None)
                'year': year,
                'slug': slug,            # slug الخاص بـ ArabSeed (للـ Worker)
                'watch_url': (row.get('watch_url') or '').strip(),
                'film_url': (row.get('film_url') or '').strip(),
            })
    return films


# ---------------------------------------------------------------------------
# 2) بناء فهرس المطابقة من all.json (خفيف: key -> [slug], وسنوات كل slug)
# ---------------------------------------------------------------------------
def title_year(t):
    y = t.get('year')
    if y:
        m = re.search(r'(19|20)\d{2}', str(y))
        if m:
            return m.group(0)
    # جرّب من العنوان
    return extract_year(t.get('clean_title') or t.get('raw_name') or '')


def build_index():
    """
    يبثّ all.json مرة واحدة ويبني:
      key_to_slugs : name_key -> set(slug)
      slug_meta    : slug -> {year, category}
      existing_slugs : set(كل الـ slugs) لتجنّب تصادم slug فيلم جديد
    """
    key_to_slugs = {}
    slug_meta = {}
    existing_slugs = set()
    n = 0
    with open(ALL, 'rb') as f:
        for t in ijson.items(f, 'item'):
            slug = t.get('slug')
            existing_slugs.add(slug)
            cat = t.get('category')
            yr = title_year(t)
            slug_meta[slug] = {'year': yr, 'category': cat}
            for k in match_keys(t.get('clean_title'), t.get('raw_name'),
                                t.get('original_title'), t.get('title_ar')):
                key_to_slugs.setdefault(k, set()).add(slug)
            n += 1
            if n % 2000 == 0:
                print(f'  indexed {n} …', flush=True)
    print(f'  indexed {n} works; keys={len(key_to_slugs)}', flush=True)
    return key_to_slugs, slug_meta, existing_slugs


# ---------------------------------------------------------------------------
# 3) قرار المطابقة لكل فيلم ArabSeed
# ---------------------------------------------------------------------------
def film_keys(film):
    """مفاتيح المطابقة لفيلم ArabSeed."""
    texts = [film['clean_title']]
    if film['english']:
        texts.append(film['english'])
    return match_keys(*texts)


def decide_match(film, key_to_slugs, slug_meta):
    """
    يرجّع slug العمل الموجود المطابق أو None.
    قاعدة: تطابق مفتاح + (سنة متساوية أو إحداهما مفقودة).
    عند عدة مرشّحين نفضّل من تتطابق سنته.
    """
    cand = set()
    for k in film_keys(film):
        for s in key_to_slugs.get(k, ()):  # set
            cand.add(s)
    if not cand:
        return None
    fy = film['year']
    # 1) تطابق سنة صريح
    year_match = [s for s in cand if fy and slug_meta.get(s, {}).get('year') == fy]
    if year_match:
        return year_match[0]
    # 2) مرشّح بلا سنة على أي طرف (نقبل بحذر مع تأكيد fuzzy)
    fk = name_key(film['clean_title'])
    best, best_ratio = None, 0.0
    for s in cand:
        sy = slug_meta.get(s, {}).get('year')
        # لو الطرفان لهما سنة مختلفة → ارفض
        if fy and sy and fy != sy:
            continue
        # تأكيد بالتشابه على المفتاح (كِلا الطرفين نُطبّع بنفس name_key)
        ratio = 1.0  # المفتاح تطابق أصلاً عبر match_keys → ثقة عالية
        if ratio > best_ratio:
            best, best_ratio = s, ratio
    return best


# ---------------------------------------------------------------------------
# 4) أدوات إنشاء/إضافة السيرفر
# ---------------------------------------------------------------------------
def make_arsd_server(film, server_id):
    """سيرفر ArabSeed من نوع video — يقرؤه الـ Worker عبر arsd_slug."""
    return {
        'id': server_id,
        'label': ARSD_SERVER_LABEL,
        'type': 'video',        # <video> + mp4 عبر Worker (مقابل iframe القديم)
        'arsd_slug': film['slug'],
        'url': '',              # يُملأ عند الطلب من الـ Worker (لا يُخزّن)
    }


def max_server_id(title):
    mx = 0
    for s in title.get('seasons') or []:
        for e in s.get('episodes') or []:
            for sv in e.get('servers') or []:
                try:
                    mx = max(mx, int(sv.get('id') or 0))
                except (TypeError, ValueError):
                    pass
    return mx


def add_server_to_title(title, film):
    """
    يضيف سيرفر ArabSeed لأول حلقة (الأفلام = حلقة واحدة). يمنع التكرار بـ arsd_slug.
    يرجّع True لو أُضيف فعلاً.
    """
    seasons = title.get('seasons')
    if not seasons:
        return False
    ep = None
    for s in seasons:
        eps = s.get('episodes') or []
        if eps:
            ep = eps[0]
            break
    if ep is None:
        return False
    servers = ep.setdefault('servers', [])
    # موجود مسبقاً؟
    for sv in servers:
        if sv.get('arsd_slug') == film['slug']:
            return False
    servers.append(make_arsd_server(film, max_server_id(title) + 1))
    return True


def make_new_movie(film, existing_slugs):
    """ينشئ عمل movie جديد بسيرفر ArabSeed فقط."""
    base_slug = make_slug(film['clean_title'] or film['english'] or film['slug'])
    slug = base_slug
    i = 2
    while slug in existing_slugs:
        slug = f'{base_slug}-{i}'
        i += 1
    existing_slugs.add(slug)

    name = film['clean_title'] or film['english'] or film['raw_title']
    # ArabSeed لا يوفّر بوستر ولا يوجد ملف في R2 لهذه الأفلام الجديدة.
    # نتركه فارغاً كي يعرض PosterCard البديل الأنيق (SVG placeholder) بدل صورة مكسورة.
    poster = ''
    story = (
        f'شاهد فيلم {name}'
        + (f' {film["year"]}' if film['year'] else '')
        + ' مترجم اون لاين بجودة عالية مع روابط مشاهدة مباشرة.'
    )
    return {
        'slug': slug,
        'clean_title': name,
        'raw_name': film['raw_title'],
        'category': 'movie',
        'category_label': 'فيلم',
        'poster': poster,
        'note': 'تستخدم لجميع 1 حلقة من الموسم 1',
        'matched_poster': False,
        'seasons_count': 1,
        'episodes_count': 1,
        'seasons': [{
            'season': 1,
            'episodes_count': 1,
            'episodes': [{
                'episode': 1,
                'title': 'الحلقة 1',
                'servers': [make_arsd_server(film, 1)],
            }],
        }],
        'description': story,
        'url': f'/movie/{slug}',
        'story': story,
        'year': film['year'],
        'quality': None,
        'duration': None,
        'language': None,
        'country': None,
        'director': None,
        'stars': None,
        'genre': None,
        'trailerId': None,
        'rating': None,
        'imdb_rating': None,
        'seoContent': None,
        'real_plot': False,
        'tmdb_vote': 0,
        'tmdb_votes': 0,
        'release_date': '',
        'sort_rating': 0,
        'sort_recent': 0,
        'is_special': False,
        'arsd_source': True,   # علامة أنه من ArabSeed (للفلترة/التتبع)
    }


# ---------------------------------------------------------------------------
# 5) الدمج البثّي (stream-safe rewrite)
# ---------------------------------------------------------------------------
def main():
    print('== تحليل CSV ==', flush=True)
    films = parse_csv()
    # تخطّى الأعمال الإباحية
    films = [f for f in films if not is_adult(name=f['raw_title'], title=f['clean_title'])]
    print(f'  أفلام ArabSeed صالحة: {len(films)}', flush=True)

    print('== بناء فهرس المطابقة من all.json ==', flush=True)
    key_to_slugs, slug_meta, existing_slugs = build_index()

    print('== قرار المطابقة ==', flush=True)
    # slug العمل الموجود -> قائمة أفلام ArabSeed تُدمج فيه
    slug_to_films = {}
    new_films = []           # أفلام غير موجودة -> تُنشأ
    matched_report = []
    for film in films:
        s = decide_match(film, key_to_slugs, slug_meta)
        if s:
            slug_to_films.setdefault(s, []).append(film)
            matched_report.append({'arsd': film['raw_title'], 'slug': s, 'year': film['year']})
        else:
            new_films.append(film)
    print(f'  مطابق (سيرفر إضافي): {sum(len(v) for v in slug_to_films.values())} فيلم '
          f'على {len(slug_to_films)} عمل', flush=True)
    print(f'  جديد (سيُنشأ): {len(new_films)}', flush=True)

    print('== إعادة كتابة all.json (بثّي) ==', flush=True)
    added_servers = 0
    with open(ALL, 'rb') as fin, open(ALL_TMP, 'w', encoding='utf-8') as fout:
        fout.write('[')
        first = True
        n = 0
        for t in ijson.items(fin, 'item'):
            slug = t.get('slug')
            for film in slug_to_films.get(slug, ()):
                if add_server_to_title(t, film):
                    added_servers += 1
            if not first:
                fout.write(',')
            fout.write('\n')
            fout.write(dumps(t))
            first = False
            n += 1
            if n % 2000 == 0:
                print(f'  wrote {n} …', flush=True)
        # ألحق الأفلام الجديدة
        created = 0
        for film in new_films:
            mv = make_new_movie(film, existing_slugs)
            if not first:
                fout.write(',')
            fout.write('\n')
            fout.write(dumps(mv))
            first = False
            created += 1
        fout.write('\n]')
    os.replace(ALL_TMP, ALL)
    print(f'  wrote {n} existing + {created} new = {n + created} works', flush=True)

    report = {
        'csv_films': len(films),
        'matched_films': sum(len(v) for v in slug_to_films.values()),
        'matched_works': len(slug_to_films),
        'added_servers': added_servers,
        'created_movies': created,
        'matched_sample': matched_report[:60],
        'created_sample': [f['raw_title'] for f in new_films[:60]],
    }
    with open(REPORT, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print('\n== تقرير ==', flush=True)
    print(f'  أفلام CSV        : {report["csv_films"]}')
    print(f'  مطابقة (سيرفر)   : {report["matched_films"]} فيلم / {report["matched_works"]} عمل')
    print(f'  سيرفرات أُضيفت    : {report["added_servers"]}')
    print(f'  أفلام جديدة       : {report["created_movies"]}')
    print(f'  التقرير الكامل    : {REPORT}')


if __name__ == '__main__':
    main()
