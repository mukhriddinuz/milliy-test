"""Reklamani bitta foydalanuvchiga yuborish (send_reklama buyrug'i ishlatadi)."""
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_keyboard(buttons):
    if not buttons:
        return None
    kb = InlineKeyboardMarkup()
    for btn in buttons:
        kb.add(InlineKeyboardButton(text=btn["text"], url=btn["url"]))
    return kb


def send_reklama(bot, reklama, user):
    """True — yuborildi, False — yuborilmadi (botni bloklaganlar nofaol qilinadi)."""
    keyboard = build_keyboard(reklama.buttons_json)
    media = {
        "image": bot.send_photo, "video": bot.send_video, "document": bot.send_document,
        "audio": bot.send_audio, "voice": bot.send_voice,
    }
    try:
        if reklama.source_message_id and reklama.source_chat_id:
            bot.copy_message(
                chat_id=user.telegram_id,
                from_chat_id=reklama.source_chat_id,
                message_id=reklama.source_message_id,
                reply_markup=keyboard,
            )
        elif reklama.message_type == "text":
            bot.send_message(user.telegram_id, reklama.parsed_text, parse_mode="HTML", reply_markup=keyboard)
        elif reklama.message_type in media:
            media[reklama.message_type](
                user.telegram_id, reklama.file_id, caption=reklama.parsed_text,
                parse_mode="HTML", reply_markup=keyboard,
            )
        else:
            return False
        return True
    except ApiTelegramException as e:
        print(f"Telegram API Exception for user {user.telegram_id}: {e}")
        if e.error_code == 403 or "Forbidden" in str(e) or "blocked" in str(e).lower():
            user.is_active = False
            user.save(update_fields=["is_active"])
        return False
    except Exception as e:
        print(f"Unexpected error in send_reklama for user {user.telegram_id}: {e}")
        return False
