"""Bot suhbat holati (reklama kutish, /register bosqichlari).

Server (Passenger) bir nechta jarayonda ishlaydi va har bir webhook so'rovi boshqa
jarayonga tushishi mumkin. Shuning uchun holat oddiy lug'atda emas, barcha jarayonlar
uchun umumiy keshda ("bot_state", fayl keshi) saqlanadi.
"""
from django.core.cache import caches

STATE_TIMEOUT = 60 * 60  # 1 soat ichida tugatilmagan jarayon unutiladi


def _cache():
    return caches["bot_state"]


def _key(kind, uid):
    return f"{kind}:{uid}"


def get_state(kind, uid):
    try:
        return _cache().get(_key(kind, uid))
    except Exception:
        return None


def set_state(kind, uid, value):
    _cache().set(_key(kind, uid), value, STATE_TIMEOUT)


def clear_state(kind, uid):
    try:
        _cache().delete(_key(kind, uid))
    except Exception:
        pass


def acquire_lock(name, timeout):
    """Bir vaqtda faqat bitta jarayon bajarishi kerak bo'lgan ish uchun qulf. Olingan bo'lsa True."""
    return _cache().add(f"lock:{name}", 1, timeout)


def release_lock(name):
    clear_state("lock", name)


def refresh_lock(name, timeout):
    """Uzoq ishda qulf muddatini uzaytiradi."""
    _cache().set(f"lock:{name}", 1, timeout)
