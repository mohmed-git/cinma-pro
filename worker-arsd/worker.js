/**
 * ArabSeed on-demand link resolver  --  Cloudflare Worker
 * ---------------------------------------------------------
 * يستخرج رابط الفيديو النهائي (mp4) لفيلم من m.arsd.bid عند الطلب.
 *
 * لماذا Worker؟
 *   - رابط الـ mp4 النهائي *مؤقت* (صلاحية 24 ساعة ويتغيّر كل طلب)، فلا يصح تخزينه.
 *   - صفحة المشغّل pl.asdplay.cam ترفض الطلب (403) بدون Referer يحتوي نطاق الموقع
 *     — الـ Worker يضيف الـ Referer من طرف السيرفر (لا يمكن للمتصفح تزييف Referer).
 *   - يتجاوز حماية الدومين/الـ CORS لأن الطلب يخرج من سيرفر Cloudflare لا من متصفح الزائر.
 *
 * السلسلة:
 *   film/watch  --GET-->  currentPlayerUrl (ثابت)  --GET(+Referer)-->  mp4 (مؤقت)
 *
 * ===== نقاط النهاية (Endpoints) =====
 *
 * 1) GET /resolve?slug=hell-in-paradise-2025
 *    GET /resolve?watch=https://m.arsd.bid/hell-in-paradise-2025/watch/
 *    GET /resolve?player=https://pl.asdplay.cam/?play=TOKEN
 *      -> JSON: { ok, mp4_url, player_url, expires_at, cached }
 *
 * 2) GET /play?slug=hell-in-paradise-2025
 *      -> 302 Redirect مباشرة إلى رابط الـ mp4 (استخدمه كـ src للمشغّل مباشرة)
 *
 * 3) GET /stream?slug=hell-in-paradise-2025
 *      -> proxy للفيديو عبر الـ Worker (يخفي رابط المصدر تماماً، يدعم Range/seek)
 *         ⚠️ يستهلك حصة نطاق الـ Worker — استخدمه فقط إذا احتجت إخفاء المصدر.
 *
 * كل النقاط تدعم CORS (يمكن استدعاؤها من أي موقع/JS).
 *
 * ===== الإعداد =====
 *   - اختياري: أنشئ KV namespace واربطه باسم  LINK_CACHE  لتخزين مؤقت للروابط.
 *   - CACHE_TTL (ثواني): مدة التخزين المؤقت (افتراضي 6 ساعات، أقل من صلاحية 24h بأمان).
 */

const SITE = "https://m.arsd.bid";
const SITE_REFERER = "https://m.arsd.bid/";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36";

const CACHE_TTL = 6 * 60 * 60; // 6 ساعات

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "*",
};

const PLAYER_RE = /currentPlayerUrl:\s*"([^"]+)"/;
const MP4_RE = /url:\s*"(https?:\/\/[^"]+\.mp4)"/;
const MP4_RE2 = /"(https?:\/\/[^"]+\/download\/\d+\/[a-z0-9]+\/[^"]+\.mp4)"/i;
// الـ timestamp في مسار الرابط = وقت انتهاء الصلاحية (Unix seconds)
const TS_RE = /\/download\/(\d+)\//;

function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS },
  });
}

async function httpGet(url, referer) {
  const headers = {
    "User-Agent": UA,
    Accept: "*/*",
    "Accept-Language": "ar,en;q=0.8",
  };
  if (referer) headers["Referer"] = referer;
  const r = await fetch(url, { headers, redirect: "follow" });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  return await r.text();
}

/** يبني رابط صفحة المشاهدة من slug أو film_url */
function watchUrlFrom({ slug, watch, film }) {
  if (watch) return watch;
  if (film) return film.replace(/\/+$/, "") + "/watch/";
  if (slug) return `${SITE}/${slug}/watch/`;
  return null;
}

/** يستخرج player_url الثابت من صفحة المشاهدة */
async function playerFromWatch(watchUrl) {
  const filmUrl = watchUrl.replace(/watch\/?$/, "");
  const html = await httpGet(watchUrl, filmUrl || SITE_REFERER);
  const m = html.match(PLAYER_RE);
  if (!m) throw new Error("currentPlayerUrl not found");
  return m[1].replace(/\\\//g, "/");
}

/** يستخرج رابط الـ mp4 المؤقت من صفحة المشغّل (يتطلب Referer) */
async function mp4FromPlayer(playerUrl) {
  const html = await httpGet(playerUrl, SITE_REFERER);
  const m = html.match(MP4_RE) || html.match(MP4_RE2);
  if (!m) throw new Error("mp4 url not found");
  return m[1].replace(/\\\//g, "/");
}

/** يحسب وقت انتهاء الصلاحية من الـ timestamp في الرابط */
function expiryFromMp4(mp4Url) {
  const m = mp4Url.match(TS_RE);
  if (!m) return null;
  return parseInt(m[1], 10); // Unix seconds
}

/** السلسلة الكاملة: (slug|watch|film|player) -> { mp4_url, player_url } */
async function resolve(params) {
  let playerUrl = params.player;
  if (!playerUrl) {
    const watchUrl = watchUrlFrom(params);
    if (!watchUrl) throw new Error("مطلوب أحد: slug / watch / film / player");
    playerUrl = await playerFromWatch(watchUrl);
  }
  const mp4Url = await mp4FromPlayer(playerUrl);
  return { player_url: playerUrl, mp4_url: mp4Url };
}

/** resolve مع تخزين مؤقت اختياري في KV */
async function resolveCached(env, params) {
  const cacheKey =
    "arsd:" + (params.slug || params.watch || params.film || params.player);

  if (env.LINK_CACHE && cacheKey) {
    const cached = await env.LINK_CACHE.get(cacheKey, "json");
    if (cached && cached.expires_at && cached.expires_at * 1000 > Date.now() + 60000) {
      return { ...cached, cached: true };
    }
  }

  const res = await resolve(params);
  const expires_at = expiryFromMp4(res.mp4_url);
  const payload = { ok: true, ...res, expires_at, cached: false };

  if (env.LINK_CACHE && cacheKey) {
    // نخزّن لمدة أقصر من الصلاحية الحقيقية بأمان
    const ttl = expires_at
      ? Math.max(60, Math.min(CACHE_TTL, expires_at - Math.floor(Date.now() / 1000) - 300))
      : CACHE_TTL;
    await env.LINK_CACHE.put(cacheKey, JSON.stringify(payload), { expirationTtl: ttl });
  }
  return payload;
}

/** proxy للفيديو مع دعم Range/seek */
async function proxyStream(request, mp4Url) {
  const range = request.headers.get("Range");
  const headers = { "User-Agent": UA, Referer: SITE_REFERER };
  if (range) headers["Range"] = range;
  const upstream = await fetch(mp4Url, { headers });

  const respHeaders = new Headers(CORS);
  for (const h of [
    "Content-Type",
    "Content-Length",
    "Content-Range",
    "Accept-Ranges",
    "Cache-Control",
  ]) {
    const v = upstream.headers.get(h);
    if (v) respHeaders.set(h, v);
  }
  if (!respHeaders.has("Content-Type")) respHeaders.set("Content-Type", "video/mp4");
  if (!respHeaders.has("Accept-Ranges")) respHeaders.set("Accept-Ranges", "bytes");

  return new Response(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const params = {
      slug: url.searchParams.get("slug") || undefined,
      watch: url.searchParams.get("watch") || undefined,
      film: url.searchParams.get("film") || undefined,
      player: url.searchParams.get("player") || undefined,
    };

    try {
      if (path === "/" || path === "/health") {
        return jsonResponse({
          ok: true,
          service: "arsd on-demand resolver",
          endpoints: ["/resolve", "/play", "/stream"],
          usage: "?slug=<film-slug>  أو  ?watch=<watch_url>  أو  ?film=<film_url>",
        });
      }

      if (path === "/resolve") {
        const res = await resolveCached(env, params);
        return jsonResponse(res);
      }

      if (path === "/play") {
        const res = await resolveCached(env, params);
        return new Response(null, {
          status: 302,
          headers: { Location: res.mp4_url, ...CORS },
        });
      }

      if (path === "/stream") {
        const res = await resolveCached(env, params);
        return proxyStream(request, res.mp4_url);
      }

      return jsonResponse({ ok: false, error: "unknown endpoint" }, 404);
    } catch (e) {
      return jsonResponse({ ok: false, error: String(e && e.message || e) }, 502);
    }
  },
};
