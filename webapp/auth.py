"""WebApp foydalanuvchisini aniqlash.

Telegram ichida ochilgan sahifa initData'ni /auth/ ga yuboradi, server imzoni tekshirib
sessiyaga yozadi. Keyingi so'rovlarda foydalanuvchi sessiyadan olinadi.
"""
from functools import wraps

from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlencode

from main.models import TelegramUser

SESSION_KEY = "tg"

# Telegram Web (web.telegram.org) sahifani iframe ichida ochadi
FRAME_ANCESTORS = "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"


def login_telegram(request, tg_user):
    request.session.cycle_key()
    request.session[SESSION_KEY] = {
        "id": int(tg_user["id"]),
        "first_name": tg_user.get("first_name", ""),
        "last_name": tg_user.get("last_name", ""),
        "username": tg_user.get("username", ""),
        "photo_url": tg_user.get("photo_url", ""),
    }


def get_telegram(request):
    tg = request.session.get(SESSION_KEY)
    if tg:
        return tg
    dev_id = getattr(settings, "WEBAPP_DEV_TELEGRAM_ID", None)
    if settings.DEBUG and dev_id:
        # Faqat lokal ishlab chiqish uchun: Telegram'siz brauzerda ochish
        login_telegram(request, {"id": int(dev_id), "first_name": "Dev"})
        return request.session[SESSION_KEY]
    return None


def allow_telegram_frame(response):
    response.xframe_options_exempt = True
    response["Content-Security-Policy"] = FRAME_ANCESTORS
    return response


def telegram_page(require_registration=False):
    """Sahifa uchun dekorator: request.tg (Telegram ma'lumotlari) va request.tg_user (TelegramUser yoki None)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            tg = get_telegram(request)
            if tg is None:
                response = render(request, "webapp/auth.html", {"next": request.get_full_path(), "hide_nav": True})
                return allow_telegram_frame(response)

            request.tg = tg
            request.tg_user = TelegramUser.objects.filter(telegram_id=tg["id"]).first()

            if request.tg_user and request.tg_user.is_banned:
                return allow_telegram_frame(render(request, "webapp/banned.html", {"hide_nav": True}, status=403))
            if require_registration and request.tg_user is None:
                url = reverse("webapp:register") + "?" + urlencode({"next": request.get_full_path()})
                return allow_telegram_frame(redirect(url))

            return allow_telegram_frame(view(request, *args, **kwargs))

        return wrapper

    return decorator
