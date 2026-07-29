# arsd-resolver — Cloudflare Worker لاستخراج روابط ArabSeed عند الطلب

هذا Worker **مستقل** عن موقع Astro. مهمته: استخراج رابط الـ mp4 الطازج
لفيلم من `m.arsd.bid` عند الطلب (الرابط مؤقت 24 ساعة ومحمي بـ Referer).

## ⚠️ مهم قبل النشر — اقرأ هذا

هذا الـ Worker شيء **منفصل تماماً** عن الموقع:
- **الموقع (Astro)** يُرفع على GitHub ويُبنى تلقائياً في **Cloudflare Pages**.
- **الـ Worker** لا يُرفع على GitHub، بل يُنشر بأمر `wrangler` مباشرة من جهازك.
- لا تخلط بينهما. الـ Worker لا علاقة له بعملية GitHub → Pages إطلاقاً.

## النشر — الطريقة الأسهل (سكربت جاهز)

**دبل كليك على `DEPLOY_WORKER.bat`** (يعمل تسجيل الدخول + النشر تلقائياً)،
أو من CMD:

```bat
cd worker-arsd
DEPLOY_WORKER.bat
```

## النشر يدوياً (إن لم يعمل السكربت)

```bash
cd worker-arsd
npx wrangler login
npx wrangler deploy -c wrangler.toml
```

> **لماذا `-c wrangler.toml`؟** إن شغّلت `npx wrangler deploy` وحده وكان
> مجلد الموقع الرئيسي فيه `wrangler.jsonc`، سيظنّ wrangler أنك تنشر الموقع
> (Pages) ويظهر الخطأ:
> `X [ERROR] Missing entry-point to Worker script or to assets directory`
> والحل: مرّر `-c wrangler.toml` صراحةً، وتأكد أنك **داخل مجلد `worker-arsd`**.

بعد النشر ستحصل على رابط بالصيغة:

```
https://arsd-resolver.<your-subdomain>.workers.dev
```

**انسخ هذا الرابط** وضعه في إعداد الموقع `ARSD_WORKER_URL`:
1. **للإنتاج**: Cloudflare Dashboard ← Pages ← مشروعك ← Settings ←
   Environment variables ← أضف `ARSD_WORKER_URL` بالقيمة، ثم **Retry deployment**.
2. **للتطوير المحلي**: في ملف `.dev.vars` بجذر مشروع الموقع.

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
