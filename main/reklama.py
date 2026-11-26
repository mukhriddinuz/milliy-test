"""Reklamani bitta foydalanuvchiga yuborish (send_reklama buyrug'i va admin ko'rinishi ishlatadi)."""
import logging
import time

from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# Bu xatolar foydalanuvchi botni bloklagani / o'chirilgani / botni hech ishga tushirmaganini bildiradi
INACTIVE_ERRORS = ("blocked", "deactivated", "chat not found", "bot can't initiate", "user not found")


def build_keyboard(buttons):
    if not buttons:
        return None
    kb = InlineKeyboardMarkup()
    for btn in buttons:
        kb.add(InlineKeyboardButton(text=btn["text"], url=btn["url"]))
    return kb


def has_custom_text(reklama):
    """Matnda [[...](...)] havola yoki [[...|...]] tugma bor — uni asl ko'rinishda nusxalab bo'lmaydi."""
    return bool(reklama.text) and (reklama.parsed_text or "") != reklama.text.strip()


def deliver(bot, reklama, chat_id):
    """Reklamani chat_id ga yuboradi. Xatolarni o'zi ushlamaydi."""
    keyboard = build_keyboard(reklama.buttons_json)
    text = reklama.parsed_text or ""

    if reklama.source_message_id and reklama.source_chat_id:
        source = {"from_chat_id": reklama.source_chat_id, "message_id": reklama.source_message_id}
        if not has_custom_text(reklama):
            # Asl xabar (formatlash, media, forward) o'zgarishsiz nusxalanadi
            return bot.copy_message(chat_id, reply_markup=keyboard, **source)
        try:
            if reklama.message_type == "text":
                # Matndagi [[...]] belgilar o'rniga tayyor havola/tugmalar bilan yuboriladi
                return bot.send_message(chat_id, text or "📢", parse_mode="HTML", reply_markup=keyboard)
            return bot.copy_message(chat_id, caption=text, parse_mode="HTML", reply_markup=keyboard, **source)
        except ApiTelegramException as e:
            if "parse" not in str(e).lower():
                raise
            # HTML belgilarda xato bo'lsa — asl xabarni nusxalaymiz
            return bot.copy_message(chat_id, reply_markup=keyboard, **source)

    media = {
        "image": bot.send_photo, "video": bot.send_video, "document": bot.send_document,
        "audio": bot.send_audio, "voice": bot.send_voice,
    }
    if reklama.message_type == "text":
        return bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=keyboard)
    if reklama.message_type in media and reklama.file_id:
        return media[reklama.message_type](chat_id, reklama.file_id, caption=text, parse_mode="HTML",
                                           reply_markup=keyboard)
    raise ValueError(f"Reklama #{reklama.pk}: yuboriladigan kontent yo'q")


def send_reklama(bot, reklama, user):
    """True — yuborildi, False — yuborilmadi (botni bloklaganlar nofaol qilinadi)."""
    for attempt in range(3):
        try:
            deliver(bot, reklama, user.telegram_id)
            return True
        except ApiTelegramException as e:
            if e.error_code == 429 and attempt < 2:
                # Telegram tezlik chegarasi: aytilgan vaqtcha kutib, qayta urinamiz
                retry_after = (e.result_json or {}).get("parameters", {}).get("retry_after", 5)
                time.sleep(min(int(retry_after) + 1, 60))
                continue
            logger.warning(f"Reklama #{reklama.pk} -> {user.telegram_id}: {e}")
            if e.error_code == 403 or any(s in str(e).lower() for s in INACTIVE_ERRORS):
                user.is_active = False
                user.save(update_fields=["is_active"])
            return False
        except Exception as e:
            logger.warning(f"Reklama #{reklama.pk} -> {user.telegram_id}: kutilmagan xato: {e}")
            return False
    return False
