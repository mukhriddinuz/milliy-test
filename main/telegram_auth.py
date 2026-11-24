"""Telegram WebApp initData imzosini tekshirish.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from django.conf import settings


def validate_init_data(init_data, bot_token=None, max_age=None):
    """initData haqiqiy bo'lsa uning maydonlarini (user — dict) qaytaradi, aks holda None.

    Imzo bot tokeni bilan tekshiriladi, shuning uchun brauzerdan kelgan
    telegram_id ni soxtalashtirib bo'lmaydi.
    """
    if not init_data or not isinstance(init_data, str):
        return None
    bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
    if max_age is None:
        max_age = settings.WEBAPP_INIT_DATA_MAX_AGE

    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None

    received_hash = fields.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        return None
    if max_age and time.time() - auth_date > max_age:
        return None

    if "user" in fields:
        try:
            fields["user"] = json.loads(fields["user"])
        except ValueError:
            return None
    if not isinstance(fields.get("user"), dict) or not fields["user"].get("id"):
        return None
    return fields


def sign_init_data(fields, bot_token=None):
    """Testlar uchun: maydonlardan imzolangan initData satrini yasaydi."""
    from urllib.parse import urlencode

    bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
    fields = {k: (json.dumps(v, separators=(",", ":")) if isinstance(v, dict) else str(v)) for k, v in fields.items()}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)
