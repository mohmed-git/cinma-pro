# arsd-resolver — Cloudflare Worker لاستخراج روابط ArabSeed عند الطلب

هذا Worker **مستقل** عن موقع Astro. مهمته: استخراج رابط الـ mp4 الطازج
لفيلم من `m.arsd.bid` عند الطلب (الرابط مؤقت 24 ساعة ومحمي بـ Referer).

## النشر (خطوة واحدة)

```bash
cd worker-arsd
npx wrangler deploy
```

بعد النشر ستحصل على رابط بالصيغة:

```
https://arsd-resolver.<your-subdomain>.workers.dev
```

**انسخ هذا الرابط** وضعه في إعداد الموقع `ARSD_WORKER_URL`
(في ملف `.dev.vars` محلياً، وفي متغيرات بيئة Cloudflare Pages للإنتاج).

## (اختياري) تفعيل الكاش عبر KV

```bash
npx wrangler kv namespace create LINK_CACHE
# انسخ الـ id واضعه في wrangler.toml (أزل # عن الأسطر) ثم:
npx wrangler deploy
```

الكاش يخزّن الرابط المستخرَج حتى قُبيل انتهاء صلاحيته، فيقلّل الطلبات لموقع المصدر.

## نقاط النهاية

| المسار | النتيجة | الاستخدام في الموقع |
|--------|---------|--------------------|
| `GET /resolve?slug=<slug>` | JSON `{ ok, mp4_url, player_url, expires_at, cached }` | **المُعتمد** — الموقع يطلبه ويضع `mp4_url` في `<video>` |
| `GET /play?slug=<slug>` | تحويل 302 مباشر إلى mp4 | بديل بسيط: `<video src=".../play?slug=...">` |
| `GET /stream?slug=<slug>` | بروكسي للفيديو عبر الـ Worker | ⚠️ غير مُوصى به افتراضياً (الفيلم ~1.24GB يمرّ عبر الـ Worker) |
| `GET /health` | JSON فحص صحة | مراقبة |

> الموقع يستخدم **`/resolve`** عمداً: الفيديو يُحمّل مباشرة من `downet.net`
> إلى متصفح الزائر (يدعم seek/Range)، والـ Worker يعالج طلباً صغيراً فقط
> (استخراج الرابط) — بدلاً من تمرير ~1.24GB لكل مشاهدة.

## أمثلة اختبار

```bash
curl "https://arsd-resolver.<sub>.workers.dev/resolve?slug=hell-in-paradise-2025"
curl "https://arsd-resolver.<sub>.workers.dev/health"
```
