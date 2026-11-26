"""Xatolar API'si — server xatolarini tahlil qilish uchun (Claude yoki dasturchi).

Kirish: ERROR_LOG_KEY kaliti bilan (admin login kerak emas):
    ?key=<kalit>                         — brauzer / web-fetch uchun
    Authorization: Bearer <kalit>        — yoki X-Error-Log-Key: <kalit>

    GET    /api/errors/                  — xatolar ro'yxati (JSON). ?text=1 — o'qish uchun oddiy matn
                                           ?since=<unix vaqt> — shu vaqtdan keyin takrorlanganlar
                                           ?limit=<son> (standart 50)
    GET    /api/errors/<fingerprint>/    — bitta xato (to'liq traceback bilan)
    DELETE /api/errors/<fingerprint>/    — xato tuzatildi, ro'yxatdan olib tashlash
    DELETE /api/errors/                  — hammasini tozalash

Kalit bo'lmasa yoki noto'g'ri bo'lsa — 404 (API borligi ham bilinmaydi).
"""
import hmac
import subprocess
import time
from functools import lru_cache

from django.conf import settings
from django.http import Http404, HttpResponse
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .errorlog import clear_errors, load_errors, render_text


def _given_key(request):
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Error-Log-Key") or request.GET.get("key") or ""


def _check_key(request):
    key = getattr(settings, "ERROR_LOG_KEY", None)
    if not key or not hmac.compare_digest(_given_key(request).encode(), key.encode()):
        raise Http404()


@lru_cache(maxsize=1)
def code_version():
    """Serverdagi kod qaysi commit'da — xatoni repo'dagi to'g'ri versiya bilan solishtirish uchun."""
    try:
        return subprocess.run(["git", "-C", str(settings.BASE_DIR), "log", "-1", "--format=%h %cI %s"],
                              capture_output=True, text=True, timeout=3).stdout.strip() or None
    except Exception:
        return None


def _entries(request):
    data = load_errors()
    entries = sorted(data.values(), key=lambda e: e.get("last_seen", 0), reverse=True)
    try:
        since = float(request.GET.get("since") or 0)
    except ValueError:
        since = 0
    if since:
        entries = [e for e in entries if e.get("last_seen", 0) >= since]
    try:
        limit = max(1, min(int(request.GET.get("limit") or 50), 100))
    except ValueError:
        limit = 50
    return data, entries[:limit]


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts)) if ts else None


def _public(entry):
    e = dict(entry)
    e["first_seen_iso"] = _iso(e.get("first_seen"))
    e["last_seen_iso"] = _iso(e.get("last_seen"))
    e.pop("issue_checked", None)
    return e


class ErrorListView(APIView):
    authentication_classes = []  # admin login emas, kalit bilan
    permission_classes = []
    renderer_classes = [JSONRenderer]  # brauzerda ham toza JSON (BrowsableAPI HTML emas)
    swagger_schema = None

    def get(self, request):
        _check_key(request)
        data, entries = _entries(request)
        if request.GET.get("text"):
            return HttpResponse(render_text({e["fingerprint"]: e for e in entries}, limit=len(entries) or 1),
                                content_type="text/plain; charset=utf-8")
        return Response({
            "server_time": _iso(time.time()),
            "code_version": code_version(),
            "total_kinds": len(data),
            "returned": len(entries),
            "hint": "Har bir xatoda 'location' — loyiha kodidagi eng ichki qator. "
                    "Tuzatilgach: DELETE /api/errors/<fingerprint>/",
            "errors": [_public(e) for e in entries],
        })

    def delete(self, request):
        _check_key(request)
        return Response({"removed": clear_errors()})


class ErrorDetailView(APIView):
    authentication_classes = []
    permission_classes = []
    renderer_classes = [JSONRenderer]  # brauzerda ham toza JSON (BrowsableAPI HTML emas)
    swagger_schema = None

    def get(self, request, fingerprint):
        _check_key(request)
        entry = load_errors().get(fingerprint)
        if entry is None:
            return Response({"error": "Bunday xato yo'q (tuzatilgan yoki o'chirilgan)"}, status=404)
        return Response({"code_version": code_version(), **_public(entry)})

    def delete(self, request, fingerprint):
        _check_key(request)
        return Response({"removed": clear_errors([fingerprint])})
