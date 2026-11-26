"""Muhim hodisalarni Telegram log guruhiga yuborish (TELEGRAM_LOG_GROUP_ID)."""
import logging
from html import escape

from django.conf import settings

logger = logging.getLogger(__name__)


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def get_device_info(request):
    ua_string = request.META.get("HTTP_USER_AGENT", "")
    try:
        from user_agents import parse
    except ImportError:
        return {"device": "Noma'lum", "type": "—", "os": "—", "browser": "—", "user_agent": ua_string[:300]}

    ua = parse(ua_string)
    device_type = "📱 Mobile" if ua.is_mobile else "📲 Tablet" if ua.is_tablet else "💻 PC"
    device = f"{ua.device.family} {ua.device.model or ''}".strip()
    if device in ("Other", "Other Other"):
        device = "Noma'lum qurilma"
    return {
        "device": device,
        "type": device_type,
        "os": f"{ua.os.family} {ua.os.version_string}".strip(),
        "browser": f"{ua.browser.family} {ua.browser.version_string}".strip(),
        "user_agent": ua_string[:300],
    }


def log_to_telegram(topic: str, text: str, request=None, user=None):
    """Log guruhiga xabar. Hech qachon xato ko'tarmaydi (asosiy ish to'xtab qolmasligi uchun)."""
    group_id = getattr(settings, "TELEGRAM_LOG_GROUP_ID", None)
    topic_id = getattr(settings, "TELEGRAM_LOG_TOPICS", {}).get(topic)
    if not group_id or not topic_id:
        return

    extra = []
    if user is not None:
        telegram_id = getattr(user, "telegram_id", "—")
        name = escape(getattr(user, "full_name", "") or "Noma'lum")
        link = f"<a href='tg://user?id={telegram_id}'>{name}</a>"
        if getattr(user, "username", None):
            link += f" (@{escape(user.username)})"
        extra += [f"\n👤 <b>Foydalanuvchi:</b> {link}", f"🆔 <b>ID:</b> <code>{telegram_id}</code>"]
    if request is not None:
        try:
            info = get_device_info(request)
            extra += [
                f"\n🌍 <b>IP:</b> {escape(str(get_client_ip(request)))}",
                f"📱 <b>Qurilma:</b> {escape(info['device'])} ({info['type']})",
                f"🖥 <b>OS:</b> {escape(info['os'])}",
                f"🌐 <b>Brauzer:</b> {escape(info['browser'])}",
            ]
        except Exception:
            pass

    full_text = text + ("\n" + "\n".join(extra) if extra else "")
    try:
        from .bot import bot

        bot.send_message(chat_id=group_id, message_thread_id=topic_id, text=full_text[:4096], parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Telegram log guruhiga yuborilmadi (topic: {topic}): {e}")
