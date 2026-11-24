import logging
import time
import traceback
from functools import wraps
from html import escape

import telebot
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from telebot import types

from .models import BlockTest, BookTest, Instructions, Reklama, RequiredChannel, TelegramUser, Test
from .regions import REGIONS
from .utils import (
    calculate_rasch, calculate_student_scores, generate_block_test_result_pdf, generate_test_result_pdf,
    hisobla_statistika,
)

logger = logging.getLogger(__name__)

bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN or "0:not-configured")
ADMIN_ID = settings.TELEGRAM_ADMIN_ID
MAX_MESSAGE_LENGTH = 4000


def webapp_url(path=""):
    return f"{settings.WEBAPP_URL}/{path.lstrip('/')}"


# ---------------------------------------------------------------------------
# Yordamchi funksiyalar
# ---------------------------------------------------------------------------

def user_send_message(telegram_id, message, markup=None):
    try:
        bot.send_message(chat_id=telegram_id, text=message, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"user_send_message da xato ({telegram_id}): {e}")


def notify_admin_error(title):
    try:
        bot.send_message(ADMIN_ID, f"⚠️ <b>{escape(title)}</b>\n\n<pre>{escape(traceback.format_exc()[-3500:])}</pre>",
                         parse_mode="HTML")
    except Exception:
        logger.exception("Adminga xatolik yuborilmadi")


def send_chunked(chat_id, header, lines):
    """Uzun ro'yxatni 4096 belgi chegarasidan oshirmay bir nechta xabarga bo'lib yuboradi."""
    current = header
    for line in lines:
        if len(current) + len(line) > MAX_MESSAGE_LENGTH:
            bot.send_message(chat_id, current, parse_mode="HTML")
            current = header
        current += line
    if current != header:
        bot.send_message(chat_id, current, parse_mode="HTML")


def check_user_membership(user_id):
    """(hamma kanallarga a'zomi, a'zo bo'lmagan kanallar ro'yxati)"""
    if not user_id:
        return False, []
    not_joined = []
    for channel in RequiredChannel.objects.filter(is_active=True):
        try:
            status = bot.get_chat_member(channel.channel_id, user_id).status
            if status not in ("creator", "administrator", "member"):
                not_joined.append(channel)
        except Exception:
            # bot kanalda admin bo'lmasa ham "a'zo emas" deb hisoblanadi
            not_joined.append(channel)
    return not not_joined, not_joined


def send_subscription_message(chat_id, not_joined):
    keyboard = types.InlineKeyboardMarkup()
    for channel in not_joined:
        url = channel.get_link()
        if url:
            keyboard.add(types.InlineKeyboardButton(
                text=f"📢 {channel.channel_username or f'ID: {channel.channel_id}'}", url=url
            ))
    keyboard.add(types.InlineKeyboardButton("✅ Tekshirish", callback_data="check_subs"))
    bot.send_message(
        chat_id,
        "🚫 *Siz hali barcha kanallarga obuna bo‘lmagansiz!*\n\nQuyidagi kanallarga obuna bo‘ling 👇",
        reply_markup=keyboard, parse_mode="Markdown",
    )


BANNED_TEXT = "🚫 Siz botda **bloklangansiz**.\n\nAgar bu xato deb o‘ylasangiz, admin bilan bog‘laning 👮‍♂️"


def check_ban(user, chat_id):
    if user.is_banned:
        bot.send_message(chat_id, BANNED_TEXT, reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
        return True
    return False


def require_subscription(handler):
    """Bloklanganlarni to'xtatadi va majburiy kanallarga obunani tekshiradi."""
    @wraps(handler)
    def wrapper(message, *args, **kwargs):
        user = TelegramUser.objects.filter(telegram_id=message.from_user.id).first()
        if user and check_ban(user, message.chat.id):
            return
        try:
            is_member, not_joined = check_user_membership(message.from_user.id)
        except Exception as e:
            logger.error(f"Membership check error: {e}")
            return handler(message, *args, **kwargs)
        if not is_member:
            return send_subscription_message(message.chat.id, not_joined)
        return handler(message, *args, **kwargs)

    return wrapper


def get_main_menu(user):
    """Admin yoki oddiy foydalanuvchi uchun asosiy menyu"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    web = lambda text, path: types.InlineKeyboardButton(text=text, web_app=types.WebAppInfo(url=webapp_url(path)))

    if user.is_admin:
        markup.add(web("📚 Kitob Test yaratish", "booktest/create/"))
        markup.add(types.InlineKeyboardButton(
            text="🛠️ Admin panel", web_app=types.WebAppInfo(url=settings.ADMIN_PANEL_URL)
        ))

    markup.add(web("🎓 Milliy sertifikat testlari", ""))
    markup.add(web("🧩 Test yaratish", "create_test/"), web("📤 Javoblarni yuborish", "send_test/"))
    markup.add(web("🧮 DTM test", "dtm/"), web("👤 Mening ma'lumotlarim", "profile/"))
    markup.add(types.InlineKeyboardButton(text="📘 Yo‘riqnoma", callback_data="note_instruction"))
    return markup


def get_register_menu():
    """Ro'yxatdan o'tmagan foydalanuvchi uchun menyu"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(
        text="📝 Ro'yxatdan o'tish", web_app=types.WebAppInfo(url=webapp_url("register/"))
    ))
    return markup


def is_admin(user_id):
    return TelegramUser.objects.filter(telegram_id=user_id, is_admin=True).exists()


def send_main_menu(chat_id, user):
    bot.send_message(chat_id, "👋 Assalomu alaykum!\n\n🏠 *Asosiy menyuga* xush kelibsiz!",
                     reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
    time.sleep(0.3)
    bot.send_message(chat_id, "👇 Quyidagilardan birini tanlang:", reply_markup=get_main_menu(user))


# ---------------------------------------------------------------------------
# /start va obuna tekshiruvi
# ---------------------------------------------------------------------------

@bot.message_handler(commands=['start'])
def start(message):
    try:
        clear_user(message.from_user.id)
        ADMIN_REKLAMA_STATE.pop(message.from_user.id, None)
        is_member, not_joined = check_user_membership(message.from_user.id)
        if not is_member:
            return send_subscription_message(message.chat.id, not_joined)

        user = TelegramUser.objects.filter(telegram_id=message.from_user.id).first()
        if user is None:
            bot.send_message(message.chat.id, "🤖 *Botga xush kelibsiz!*",
                             reply_markup=types.ReplyKeyboardRemove(), parse_mode="Markdown")
            time.sleep(0.3)
            bot.send_message(message.chat.id, "📝 Iltimos, ro‘yxatdan o‘ting:", reply_markup=get_register_menu())
            return
        if check_ban(user, message.chat.id):
            return
        send_main_menu(message.chat.id, user)
    except Exception:
        logger.exception("start command da xato:")
        bot.send_message(message.chat.id, "💥 *Xatolik yuz berdi!*\n\nIltimos, qayta urinib ko‘ring 🔁",
                         parse_mode="Markdown")
        notify_admin_error("/start xatosi")


@bot.callback_query_handler(func=lambda call: call.data == "check_subs")
def check_subs_callback(call):
    try:
        is_member, _ = check_user_membership(call.from_user.id)
        if not is_member:
            return bot.answer_callback_query(call.id, text="🚫 Siz hali barcha kanallarga obuna bo‘lmadingiz!",
                                             show_alert=True)

        user = TelegramUser.objects.filter(telegram_id=call.from_user.id).first()
        if user is None:
            bot.edit_message_text(
                chat_id=call.message.chat.id, message_id=call.message.message_id,
                text="✅ A'zo bo'lganingiz uchun rahmat!\n\n📝 Endi ro‘yxatdan o‘tishingiz kerak:",
            )
            bot.send_message(call.message.chat.id, "👇 Quyidagi tugma orqali ro‘yxatdan o‘ting:",
                             reply_markup=get_register_menu())
        else:
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                  text="🎉 Ajoyib! Siz barcha kanallarga obuna bo‘ldingiz.")
            bot.send_message(call.message.chat.id,
                             "🏠 *Asosiy menyuga* xush kelibsiz!\n\n👇 Quyidagilardan birini tanlang:",
                             reply_markup=get_main_menu(user), parse_mode="Markdown")
    except Exception:
        logger.exception("check_subs_callback da xato:")
        bot.answer_callback_query(call.id, text="💥 Xatolik yuz berdi. Iltimos, qayta urinib ko‘ring 🔁",
                                  show_alert=True)
        notify_admin_error("Obuna tekshiruvi xatosi")


# ---------------------------------------------------------------------------
# Milliy sertifikat testlari: /natija_<kod>, /yakunlash_<kod>
# ---------------------------------------------------------------------------

@bot.message_handler(regexp=r"^/natija_\d+$")
def handle_results(message):
    try:
        test = Test.objects.get(id=int(message.text.split("_")[1]))
        results = test.results.select_related("user").order_by("-percentage")
        if not results.exists():
            return bot.reply_to(message, "❌ Bu test uchun natijalar yo'q.")
        send_chunked(
            message.chat.id,
            f"📊 <b>{escape(test.title)}</b> natijalari:\n\n",
            [f"{i}. {escape(str(r.user))} - ✅ {r.correct_answers}/{r.total_questions}\n"
             for i, r in enumerate(results, start=1)],
        )
    except Test.DoesNotExist:
        bot.reply_to(message, "❌ Bunday test topilmadi.")
    except Exception as e:
        logger.exception("natija xatosi")
        bot.reply_to(message, f"❌ Xatolik yuz berdi: {e}")


@bot.message_handler(regexp=r"^/yakunlash_\d+$")
def handle_stop(message):
    try:
        test = Test.objects.select_related("creator").get(id=int(message.text.split("_")[1]))

        if message.from_user.id != test.creator.telegram_id:
            return bot.reply_to(message, "❌ Siz bu testni to‘xtata olmaysiz.")
        if not test.is_active:
            return bot.reply_to(message, "⛔ Test allaqachon to‘xtatilgan.")
        if test.results.count() <= 5:
            return bot.reply_to(message, "⛔ Testda kamida 5 ta ishtirokchi bo‘lishi kerak.")

        test.is_active = False
        test.save()
        bot.reply_to(message, f"✅ <b>{escape(test.title)}</b> testi yopildi.", parse_mode="HTML")

        results = list(test.results.select_related('user'))
        savol_ballari = calculate_rasch(test.correct_answers or [], len(results))
        test.scores = savol_ballari
        test.save(update_fields=["scores", "updated_at"])

        scores = []
        for result in results:
            ball = calculate_student_scores(result, savol_ballari)
            # Natijani bazada ham saqlaymiz (admin panel va statistika uchun)
            result.total_ball = round(ball["jami_ball"], 2)
            result.question_weights = savol_ballari
            result.earned_points = ball["toplangan_ballar"]
            result.save(update_fields=["total_ball", "question_weights", "earned_points"])
            scores.append(ball)

        calculate = hisobla_statistika(scores)
        statistika = calculate['statistika']
        text = f"""
🏁 <b>Test yakunlandi!</b>

📘 <b>Test:</b> {escape(test.title)}
👨‍🏫 <b>Muallif:</b> {escape(test.creator.full_name)}
🆔 <b>Kod:</b> {test.id}
📝 <b>Savollar soni:</b> {test.questions_count} ta
👥 <b>Qatnashuvchilar:</b> {len(results)} ta

📊 <b>Statistika:</b>
🏅 A+ : {statistika['A+']}
🥇 A  : {statistika['A']}
🥈 B+ : {statistika['B+']}
🥉 B  : {statistika['B']}
🎖 C+ : {statistika['C+']}
🎗 C  : {statistika['C']}
⚠️ Sertifikat ololmaganlar: {statistika['not_sertificate']}
"""
        pdf_buffer = generate_test_result_pdf(test, calculate['natijalar'])
        pdf_buffer.name = f"test_{test.id}_natijalar.pdf"
        bot.send_document(chat_id=message.chat.id, document=pdf_buffer, caption=text, parse_mode="HTML")
    except Test.DoesNotExist:
        bot.reply_to(message, "❌ Bunday test topilmadi.")
    except Exception as e:
        logger.exception("yakunlash xatosi")
        bot.reply_to(message, f"❌ Xatolik yuz berdi: {e}")
        notify_admin_error("/yakunlash xatosi")


# ---------------------------------------------------------------------------
# DTM (blok) testlari: /natijablock_<kod>, /stop_block_<kod>
# ---------------------------------------------------------------------------

@bot.message_handler(regexp=r"^/natijablock_\d+$")
def handle_block_results(message):
    try:
        test = BlockTest.objects.get(id=int(message.text.split("_")[1]))
        results = test.results.select_related('user').order_by("-total_score")
        if not results.exists():
            return bot.reply_to(message, "❌ Bu test uchun natijalar yo'q.")
        send_chunked(
            message.chat.id,
            f"📊 <b>Blok Test {test.id}</b> natijalari:\n\n",
            [f"{i}. {escape(r.user.full_name)} - ✅ {r.correct_answers} - ⭐️ {r.total_score}\n"
             for i, r in enumerate(results, start=1)],
        )
    except BlockTest.DoesNotExist:
        bot.reply_to(message, "❌ Bunday Blok Test topilmadi.")
    except Exception as e:
        logger.exception("natijablock xatosi")
        bot.reply_to(message, f"❌ Xatolik yuz berdi: {e}")


@bot.message_handler(regexp=r"^/stop_block_\d+$")
def handle_stop_block(message):
    try:
        test = BlockTest.objects.select_related("creator").get(id=int(message.text.split("_")[2]))
        if not test.creator or message.from_user.id != test.creator.telegram_id:
            return bot.reply_to(message, "❌ Siz bu testni to‘xtata olmaysiz.")
        if not test.is_active:
            return bot.reply_to(message, "⛔ Test allaqachon to‘xtatilgan.")

        test.is_active = False
        test.save(update_fields=["is_active"])
        bot.reply_to(message, f"✅ <b>Blok Test {test.id}</b> yopildi.", parse_mode="HTML")

        results = test.results.select_related('user').order_by('-total_score')
        natijalar = [
            {"rank": i, "full_name": r.user.full_name, "correct_answers": r.correct_answers,
             "score": round(r.total_score, 1)}
            for i, r in enumerate(results, start=1)
        ]
        pdf_buffer = generate_block_test_result_pdf(test, natijalar)
        pdf_buffer.name = f"block_test_{test.id}_natijalar.pdf"
        bot.send_document(
            chat_id=message.chat.id, document=pdf_buffer, parse_mode="HTML",
            caption=f"🏁 <b>Blok Test yakunlandi!</b>\n\n🆔 <b>Kod:</b> {test.id}\n"
                    f"👥 <b>Qatnashuvchilar:</b> {len(natijalar)} ta",
        )
    except BlockTest.DoesNotExist:
        bot.reply_to(message, "❌ Bunday Blok Test topilmadi.")
    except Exception as e:
        logger.exception("stop_block xatosi")
        bot.reply_to(message, f"❌ Xatolik yuz berdi: {e}")


# ---------------------------------------------------------------------------
# Kitob testlari: /kitobnatija_<kod>
# ---------------------------------------------------------------------------

@bot.message_handler(regexp=r"^/kitobnatija_\d+$")
def handle_booktest_results(message):
    test = BookTest.objects.filter(slug=message.text.split("_")[1]).select_related("creator").first()
    if test is None:
        return bot.reply_to(message, "❌ Bunday kitob testi topilmadi.")
    if message.from_user.id != test.creator.telegram_id and not is_admin(message.from_user.id):
        return bot.reply_to(message, "❌ Bu test natijalarini faqat muallif ko‘ra oladi.")
    results = test.results.select_related("user").order_by("-score")
    if not results.exists():
        return bot.reply_to(message, "❌ Bu test uchun natijalar yo'q.")
    send_chunked(
        message.chat.id,
        f"📚 <b>{escape(test.title)}</b> (kod {test.slug}) natijalari:\n\n",
        [f"{i}. {escape(r.user.full_name)} - ✅ {r.correct_answers}/{r.total_questions} - ⭐️ {r.score} ({r.grade})\n"
         for i, r in enumerate(results, start=1)],
    )


# ---------------------------------------------------------------------------
# Yo'riqnoma
# ---------------------------------------------------------------------------

@bot.callback_query_handler(func=lambda call: call.data == "note_instruction")
def note_instruction_callback(call):
    try:
        instruction = Instructions.objects.first()
        if not instruction:
            return bot.answer_callback_query(call.id, text="ℹ️ Hozircha yo‘riqnoma mavjud emas.", show_alert=True)
        bot.send_message(call.message.chat.id, f"📘 <b>Yo‘riqnoma:</b>\n\n{instruction.content}", parse_mode="HTML")
        bot.answer_callback_query(call.id, text="📖 Yo‘riqnoma yuborildi!")
    except Exception as e:
        logger.error(f"note_instruction_callback da xato: {e}")
        bot.answer_callback_query(call.id, text="💥 Xatolik yuz berdi. Iltimos, qayta urinib ko‘ring.",
                                  show_alert=True)


# ---------------------------------------------------------------------------
# Reklama: /reklama -> kontent -> tasdiqlash -> navbat (manage.py send_reklama yuboradi)
# ---------------------------------------------------------------------------

ADMIN_REKLAMA_STATE = {}


@bot.message_handler(commands=["reklama"])
def reklama_start(message):
    if not is_admin(message.from_user.id):
        return
    ADMIN_REKLAMA_STATE[message.from_user.id] = "waiting_content"
    bot.send_message(
        message.chat.id,
        "📢 <b>Reklama yuborish</b>\n\n"
        "1️⃣ Matn / media yuboring\n"
        "2️⃣ Yoki postni <b>forward</b> qiling\n\n"
        "🔗 Link:\n[[Matn](https://t.me/nsd_corporation)]\n"
        "🔘 Tugma:\n[[Tugma|https://t.me/nsd_corporation]]\n\n"
        "❗️Reklama barcha foydalanuvchilarga yuboriladi. Bekor qilish: /bekor",
        parse_mode="HTML",
    )


def reklama_confirm_keyboard(reklama_id):
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("✅ Yuborish", callback_data=f"reklama_ok:{reklama_id}"),
        types.InlineKeyboardButton("❌ Bekor qilish", callback_data=f"reklama_no:{reklama_id}"),
    )
    return kb


@bot.message_handler(
    func=lambda m: ADMIN_REKLAMA_STATE.get(m.from_user.id) == "waiting_content",
    content_types=["text", "photo", "video", "document", "audio", "voice", "animation", "sticker", "video_note"],
)
def reklama_receive(message):
    admin_id = message.from_user.id
    ADMIN_REKLAMA_STATE.pop(admin_id, None)
    if not is_admin(admin_id):
        return
    if message.text and message.text.strip() == "/bekor":
        return bot.send_message(message.chat.id, "❌ Reklama bekor qilindi.")

    reklama = Reklama.objects.create(
        admin_user_id=admin_id,
        status="draft",
        source_message_id=message.message_id,
        source_chat_id=message.chat.id,
        message_type=message.content_type if message.content_type in dict(Reklama.TYPE) else "text",
        text=message.text or message.caption or "",
    )
    total = TelegramUser.objects.filter(is_active=True).count()
    try:
        from .reklama import build_keyboard

        bot.send_message(message.chat.id, "👇 Reklama ko‘rinishi:")
        bot.copy_message(message.chat.id, message.chat.id, message.message_id,
                         reply_markup=build_keyboard(reklama.buttons_json))
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Ko‘rinishni chiqarib bo‘lmadi: {escape(str(e))}")
    bot.send_message(
        message.chat.id,
        f"🆔 Reklama #{reklama.id}\n👥 {total} ta faol foydalanuvchiga yuboriladi.\n\nTasdiqlaysizmi?",
        reply_markup=reklama_confirm_keyboard(reklama.id),
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith(("reklama_ok:", "reklama_no:")))
def reklama_confirm(call):
    if not is_admin(call.from_user.id):
        return bot.answer_callback_query(call.id, "❌ Ruxsat yo‘q", show_alert=True)
    action, reklama_id = call.data.split(":")
    reklama = Reklama.objects.filter(id=reklama_id, status="draft").first()
    if reklama is None:
        return bot.answer_callback_query(call.id, "Bu reklama allaqachon ko‘rib chiqilgan.", show_alert=True)
    if action == "reklama_ok":
        reklama.status = "ready"
        reklama.save(update_fields=["status"])
        text = f"✅ Reklama #{reklama.id} navbatga qo‘yildi. Yuborish jarayoni haqida shu yerda xabar beriladi."
    else:
        reklama.status = "cancelled"
        reklama.save(update_fields=["status"])
        text = f"❌ Reklama #{reklama.id} bekor qilindi."
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id)


# ---------------------------------------------------------------------------
# Bot ichida ro'yxatdan o'tish: /register, profil: /profile, /me
# ---------------------------------------------------------------------------

user_data = {}


def get_user(uid):
    if uid not in user_data:
        user_data[uid] = {"step": "name", "data": {}, "message_id": None, "call_message_id": None}
    return user_data[uid]


def clear_user(uid):
    user_data.pop(uid, None)


def build_text(uid, extra=""):
    d = user_data[uid]["data"]
    return (
        "📋 Foydalanuvchi ma'lumotlari olinmoqda:\n\n"
        f"👤 Ismi: {d.get('name', '')}\n"
        f"📝 Familiyasi: {d.get('last_name', '')}\n"
        f"👨‍👩‍👦 Sharifi: {d.get('father_name', '')}\n"
        f"📞 Telefon: {d.get('phone', '')}\n"
        f"🌍 Viloyat: {d.get('region', '')}\n"
        f"🏘 Tuman: {d.get('district', '')}\n"
        f"{extra}"
    )


def safe_delete(chat_id, message_id):
    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass


@bot.message_handler(commands=['profile', 'me'])
@require_subscription
def show_profile(message):
    user = TelegramUser.objects.filter(telegram_id=message.from_user.id).first()
    if user is None:
        return bot.send_message(message.chat.id, "❌ Siz hali ro'yxatdan o'tmagansiz.\n\nRo'yxatdan o'tish: /register")
    bot.send_message(
        message.chat.id,
        "📋 <b>Sizning profilingiz:</b>\n\n"
        f"🆔 ID: <b>{user.telegram_id}</b>\n"
        f"👤 Ismi: <b>{escape(user.name)}</b>\n"
        f"📝 Familiya: <b>{escape(user.surname)}</b>\n"
        f"👨‍👩‍👦 Sharifi: <b>{escape(user.father_name or '')}</b>\n"
        f"📞 Telefon: <b>{user.phone}</b>\n"
        f"🌍 Viloyat: <b>{escape(user.region)}</b>\n"
        f"🏘 Tuman: <b>{escape(user.district)}</b>\n"
        f"📅 Ro'yxatdan o'tgan: <b>{timezone.localtime(user.created_at):%d.%m.%Y}</b>\n",
        parse_mode="HTML",
    )


@bot.message_handler(commands=["register"])
@require_subscription
def register_start(message):
    uid = message.from_user.id
    clear_user(uid)
    u = get_user(uid)
    msg = bot.send_message(
        message.chat.id,
        "📋 Foydalanuvchi ma'lumotlari olinmoqda:\n\nIsmingizni kiriting:\n\n(bekor qilish: /bekor)",
    )
    u["message_id"] = msg.message_id


@bot.message_handler(func=lambda m: m.from_user.id in user_data, content_types=["text"])
def register_steps(message):
    uid = message.from_user.id
    u = get_user(uid)
    text = (message.text or "").strip()

    if text == "/bekor" or text.startswith("/"):
        clear_user(uid)
        return bot.send_message(message.chat.id, "❌ Ro'yxatdan o'tish bekor qilindi.",
                                reply_markup=types.ReplyKeyboardRemove())
    safe_delete(message.chat.id, message.message_id)

    steps = {"name": ("last_name", "Familiyangizni kiriting:"),
             "last_name": ("father_name", "Sharifingizni kiriting:")}
    try:
        if u["step"] in ("name", "last_name", "father_name"):
            if not text or len(text) > 100:
                return bot.send_message(message.chat.id, "❗️ 1–100 belgidan iborat matn kiriting.")
            u["data"][u["step"]] = text
            if u["step"] == "father_name":
                u["step"] = "phone"
                kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
                kb.add(types.KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True))
                bot.edit_message_text(chat_id=message.chat.id, message_id=u["message_id"],
                                      text=build_text(uid, "\nTelefon raqamingizni yuboring:"))
                bot.send_message(message.chat.id, "👇 Tugma orqali yuboring:", reply_markup=kb)
                return
            u["step"], prompt = steps[u["step"]]
            bot.edit_message_text(chat_id=message.chat.id, message_id=u["message_id"],
                                  text=build_text(uid, "\n" + prompt))
        elif u["step"] == "phone":
            bot.send_message(message.chat.id, "👇 Telefon raqamni pastdagi tugma orqali yuboring.")
        else:
            bot.send_message(message.chat.id, "👆 Viloyat va tumanni tugmalar orqali tanlang.")
    except Exception:
        logger.exception("register_steps xatosi")
        bot.send_message(message.chat.id, "❌ Xatolik yuz berdi. Iltimos /register ni qayta bosing.")


@bot.message_handler(content_types=["contact"])
def get_phone(message):
    uid = message.from_user.id
    if uid not in user_data or user_data[uid]["step"] != "phone":
        return
    if message.contact.user_id and message.contact.user_id != uid:
        return bot.send_message(message.chat.id, "❗️ Faqat o‘zingizning raqamingizni yuboring.")

    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    if not phone.startswith("+998"):
        return bot.send_message(message.chat.id, "❌ Faqat O'zbekiston raqami!")

    u = get_user(uid)
    u["data"]["phone"] = phone
    u["step"] = "region"
    safe_delete(message.chat.id, message.message_id)
    try:
        tmp = bot.send_message(message.chat.id, "✅", reply_markup=types.ReplyKeyboardRemove())
        safe_delete(message.chat.id, tmp.message_id)
    except Exception:
        pass

    keyboard = types.InlineKeyboardMarkup()
    for r in REGIONS:
        keyboard.add(types.InlineKeyboardButton(r, callback_data=f"region:{r}"))
    msg = bot.send_message(message.chat.id, "Viloyatingizni tanlang:", reply_markup=keyboard)
    u["call_message_id"] = msg.message_id
    bot.edit_message_text(chat_id=message.chat.id, message_id=u["message_id"], text=build_text(uid))


@bot.callback_query_handler(func=lambda c: c.data.startswith(("region:", "district:")))
def location_callback(call):
    uid = call.from_user.id
    if uid not in user_data:
        return bot.answer_callback_query(call.id, "❌ Sessiya tugagan. /register ni qayta bosing")
    try:
        u = get_user(uid)
        key, value = call.data.split(":", 1)
        if key == "region" and value not in REGIONS:
            return bot.answer_callback_query(call.id, "❌ Noto‘g‘ri viloyat")
        if key == "district" and value not in REGIONS.get(u["data"].get("region"), []):
            return bot.answer_callback_query(call.id, "❌ Avval viloyatni tanlang")
        u["data"][key] = value

        if key == "region":
            u["step"] = "district"
            keyboard = types.InlineKeyboardMarkup()
            for d in REGIONS[value]:
                keyboard.add(types.InlineKeyboardButton(d, callback_data=f"district:{d}"))
            bot.edit_message_text("Tumaningizni tanlang:", call.message.chat.id, call.message.message_id,
                                  reply_markup=keyboard)
            bot.edit_message_text(chat_id=call.message.chat.id, message_id=u["message_id"], text=build_text(uid))
        else:
            save_user(call)
    except Exception:
        logger.exception("location_callback xatosi")
        bot.answer_callback_query(call.id, "❌ Xatolik yuz berdi")


def save_user(call):
    uid = call.from_user.id
    chat_id = call.message.chat.id
    u = user_data.get(uid)
    if not u:
        return
    d = u["data"]
    safe_delete(chat_id, u.get("message_id"))
    safe_delete(chat_id, u.get("call_message_id"))

    try:
        user, _ = TelegramUser.objects.update_or_create(
            telegram_id=uid,
            defaults={
                "username": (call.from_user.username or "")[:50],
                "name": d["name"],
                "surname": d["last_name"],
                "father_name": d["father_name"],
                "phone": d["phone"],
                "region": d["region"],
                "district": d["district"],
            },
        )
    except Exception:
        logger.exception("save_user xatosi")
        return bot.send_message(chat_id, "❌ Ma'lumotni saqlashda xatolik yuz berdi. Iltimos /register ni qayta bosing.")
    finally:
        clear_user(uid)

    bot.send_message(
        chat_id,
        "✅ Ro'yxatdan o'tish yakunlandi!\n\n"
        f"🆔 ID: {uid}\n"
        f"👤 Ismi: {user.name}\n"
        f"📝 Familiya: {user.surname}\n"
        f"👨‍👩‍👦 Sharifi: {user.father_name}\n"
        f"📞 Telefon: {user.phone}\n"
        f"🌍 Viloyat: {user.region}\n"
        f"🏘 Tuman: {user.district}\n"
        f"📅 Ro'yxatdan o'tgan: {timezone.localtime(user.created_at):%d.%m.%Y}",
    )
    bot.send_message(chat_id, "👇 Quyidagilardan birini tanlang:", reply_markup=get_main_menu(user))


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@csrf_exempt
def webhook(request):
    if request.method != "POST":
        return JsonResponse({"ok": False})
    # setWebhook(secret_token=...) bilan o'rnatilgan bo'lsa, soxta so'rovlarni rad etamiz
    secret = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", None)
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return JsonResponse({"ok": False}, status=403)
    try:
        update = telebot.types.Update.de_json(request.body.decode("UTF-8"))
        bot.process_new_updates([update])
        return JsonResponse({"ok": True})
    except Exception as e:
        logger.error(f"webhook da xato: {e}")
        return JsonResponse({"ok": False, "error": str(e)})
