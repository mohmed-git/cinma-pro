@echo off
chcp 65001 >nul
REM ============================================================
REM  نشر Worker حلّال روابط ArabSeed على Cloudflare
REM  شغّل هذا الملف من داخل مجلد worker-arsd (دبل كليك أو من CMD)
REM ============================================================
cd /d "%~dp0"

echo.
echo ============================================================
echo   نشر ArabSeed Resolver Worker
echo   المجلد الحالي: %CD%
echo ============================================================
echo.

REM التأكد من وجود ملفات الـ Worker
if not exist "worker.js" (
  echo [خطأ] لم يتم العثور على worker.js في هذا المجلد.
  echo تأكد أنك تشغّل هذا الملف من داخل مجلد worker-arsd الصحيح.
  pause
  exit /b 1
)
if not exist "wrangler.toml" (
  echo [خطأ] لم يتم العثور على wrangler.toml في هذا المجلد.
  pause
  exit /b 1
)

echo [1/2] تسجيل الدخول إلى Cloudflare (سيفتح المتصفح إن لزم)...
call npx wrangler login

echo.
echo [2/2] نشر الـ Worker...
REM  -c wrangler.toml  يجبر wrangler على استخدام إعداد الـ Worker (وليس إعداد الموقع)
call npx wrangler deploy -c wrangler.toml

echo.
echo ============================================================
echo   انتهى. انسخ الرابط الظاهر أعلاه بالشكل:
echo     https://arsd-resolver.^<اسم-حسابك^>.workers.dev
echo   ثم ضعه في متغيّر البيئة ARSD_WORKER_URL داخل:
echo   Cloudflare Dashboard ^> Pages ^> مشروعك ^> Settings ^>
echo   Environment variables  ثم اعمل Retry deployment للموقع.
echo ============================================================
echo.
pause
