"""Test yaratish va javob topshirish mantig'i.

REST API (main/views.py), WebApp sahifalari (webapp/views.py) va bot shu funksiyalardan
foydalanadi, shuning uchun mantiq bitta joyda turadi.
"""
from html import escape

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from telebot import types

from .bot import bot, user_send_message
from .logger_send import log_to_telegram
from .models import (
    BlockTestResult, BookTest, BookTestResult, MANDATORY_POINT, Test, TestResult, dtm_subject_name,
)


class SubmissionError(Exception):
    """Javobni qabul qilib bo'lmaydigan holat (foydalanuvchiga ko'rsatiladigan matn bilan)."""


def bot_link():
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}"


def test_open_error(test):
    """Testga javob yuborish mumkin bo'lmasa sababini qaytaradi, aks holda None."""
    if not test.is_active:
        return "Bu test yakunlangan, javob qabul qilinmaydi."
    if test.start_time and test.start_time > timezone.now():
        local = timezone.localtime(test.start_time)
        return f"Test hali boshlanmagan. Boshlanish vaqti: {local:%d.%m.%Y %H:%M}"
    return None


# ---------------------------------------------------------------------------
# Milliy sertifikat testlari
# ---------------------------------------------------------------------------

def notify_test_created(test):
    """Test yaratilganda muallifga ikki xabar yuboradi: ma'lumot va o'quvchilarga tayyor e'lon."""
    creator_id = test.creator.telegram_id
    name = escape(test.creator.full_name)
    subject = escape(test.subject.name)

    user_send_message(creator_id, f"""
✅ <b>TEST BAZAGA QO‘SHILDI!</b>

📋 Test kodi: <code>{test.id}</code>
📘 Fan nomi: {subject}
🧮 Savollar soni: {test.questions_count}
✍️ Test muallifi: {name}

📊 Natijalarni ko‘rish: /natija_{test.id}
🏁 Testni yakunlash: /yakunlash_{test.id}
━━━━━━━━━━━━━━━━━━━━━━

📢 Quyidagi tayyor izohni o‘quvchilaringizga yuborishingiz mumkin 👇👇👇
""")

    username = settings.TELEGRAM_BOT_USERNAME
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Testga o'tish", url=bot_link()))
    user_send_message(creator_id, f"""<b>🧠 TEST BOSHLANDI!</b>

👤 <b>Test muallifi:</b>
<a href='tg://user?id={creator_id}'>{name}</a>

📘 <b>Test nomi:</b> {subject} MS test
🧮 <b>Savollar soni:</b> {test.questions_count} ta
🆔 <b>Test kodi:</b> <code>{test.id}</code>

━━━━━━━━━━━━━━━━━━━━━━

📢 <b>Javoblaringizni yuboring:</b>
➡️ <a href="{bot_link()}">@{username}</a>

🚀 Omad tilaymiz! To‘g‘ri javoblaringiz ko‘p bo‘lsin! 💪
""", markup=markup)


def submit_test_answers(test, user, user_answers, request=None):
    """Javoblarni tekshiradi, natijani saqlaydi va xabarlarni yuboradi.

    Qayta topshirilsa avvalgi natija yangilanadi. SubmissionError ko'tarishi mumkin.
    """
    reason = test_open_error(test)
    if reason:
        raise SubmissionError(reason)
    if not isinstance(user_answers, dict) or not user_answers:
        raise SubmissionError("Kamida bitta savolga javob bering.")

    with transaction.atomic():
        test = Test.objects.select_for_update().get(pk=test.pk)
        result = test.check_answer(user_answers, user=user)
        if "error" in result:
            raise SubmissionError(f"Javoblarni tekshirishda xatolik: {result['error']}")
        test_result, _ = TestResult.objects.update_or_create(
            user=user,
            test=test,
            defaults={
                "correct_answers": result["correct"],
                "total_questions": result["total"],
                "percentage": result["percentage"],
                "user_answers": result["answers"],
            },
        )

    subject = escape(test.subject.name)
    user_send_message(user.telegram_id, f"""
<b>📊 TEST NATIJASI</b>

🆔 <b>Test kodi:</b> <code>{test.id}</code>
📚 <b>Fan nomi:</b> {subject}
📋 <b>Umumiy savollar soni:</b> {result['total']}
✅ <b>To‘g‘ri javoblar:</b> {result['correct']}
📈 <b>Foiz ko‘rsatkich:</b> {result['percentage']}%

━━━━━━━━━━━━━━━━━━━

🎯 Siz <b>{subject}</b> fanidan o‘tkazilgan testda
{result['total']} ta savoldan <b>{result['correct']}</b> tasiga to‘g‘ri javob berdingiz.

💪 Bu hali boshlanishi — harakatni davom ettiring!
Keyingi testlarda albatta yuqori natijalarga erishasiz. 🚀

━━━━━━━━━━━━━━━━━━━

📢 <b>Umumiy natijalar test yakunlangandan so‘ng yuboriladi.</b>

🗓️ <b>Sana va vaqt:</b> {timezone.localtime():%Y-%m-%d %H:%M:%S}
""")

    answers_str = "\n".join(f"{k}: {v}" for k, v in user_answers.items())
    log_to_telegram("results", (
        f"✅ <b>Test ishlandi</b>\n📚 Fan: {subject} - {test.id}\n📋 Test: {escape(test.title)}\n"
        f"📊 Natija: {result['correct']}/{result['total']} ({result['percentage']}%)\n"
        f"📝 <b>Javoblar:</b>\n{escape(answers_str)}"
    ), request=request, user=user)

    # Muallifga: yangi javob keldi
    user_send_message(test.creator.telegram_id, f"""
<b>✅ Testga javoblar qabul qilindi!</b>

🆔 <b>Test kodi:</b> <code>{test.id}</code>
👤 <b>Test topshiruvchi:</b>
<a href='tg://user?id={user.telegram_id}'>{escape(user.full_name)}</a>

━━━━━━━━━━━━━━━━━━━

📊 <b>Natijalarni ko‘rish:</b> /natija_{test.id}
🛑 <b>Testni yakunlash:</b> /yakunlash_{test.id}

━━━━━━━━━━━━━━━━━━━

🕓 <i>Natijalar test yakunlangandan so‘ng umumiy tahlilga qo‘shiladi.</i>
""")
    return result, test_result


# ---------------------------------------------------------------------------
# DTM (blok) testlari
# ---------------------------------------------------------------------------

# Asosiy (tanlov) fanlar: meta kaliti -> nomi
DTM_OPTIONAL_SUBJECTS = [
    ("mathematics", "Matematika"),
    ("physics", "Fizika"),
    ("english_language", "Ingliz tili"),
    ("arabic_language", "Arab tili"),
    ("russian_language", "Rus tili"),
    ("turkic_language", "Turk tili"),
    ("biology", "Biologiya"),
    ("chemistry", "Kimyo"),
    ("mother_tongue", "Ona tili"),
    ("uzbekistan_history", "O‘zbekiston tarixi"),
    ("geography", "Geografiya"),
    ("law", "Huquq"),
]
# Majburiy fanlar: (meta kaliti, savol raqamlari)
DTM_MANDATORY_BLOCKS = [("ona_tili", range(1, 11)), ("math_mandatory", range(11, 21)), ("history", range(21, 31))]
DTM_MAIN_BLOCKS = [(range(31, 61), 3.1), (range(61, 91), 2.1)]


def build_block_meta(main_1, main_2, answers):
    """Yaratish formasidan meta tuzadi (eski frontend formatida: savollar 1..90 raqamlanadi).

    answers: {"ona_tili": {1: "A", ...}, "math_mandatory": {...}, "history": {...}, "main_1": {...}, "main_2": {...}}
    bu yerda har blok ichida savollar 1 dan boshlab raqamlangan.
    """
    meta = {}
    for key, numbers in DTM_MANDATORY_BLOCKS:
        meta[key] = {"type": "mandatory",
                     "questions": {str(n): answers[key][str(i)] for i, n in enumerate(numbers, start=1)}}
    for (numbers, point), subject, block in zip(DTM_MAIN_BLOCKS, (main_1, main_2), ("main_1", "main_2")):
        meta[subject] = {"type": "optional", "point_per_question": point,
                         "questions": {str(n): answers[block][str(i)] for i, n in enumerate(numbers, start=1)}}
    return meta


def notify_block_test_created(test):
    creator = test.creator
    subjects_str = escape(", ".join(dtm_subject_name(k) for k in test.meta)) or "Noma'lum"
    user_send_message(creator.telegram_id, (
        f"✅ <b>Blok Test muvaffaqiyatli yaratildi!</b>\n\n"
        f"🆔 <b>Test ID:</b> <code>{test.id}</code>\n"
        f"📚 <b>Fanlar:</b> {subjects_str}\n"
        f"👤 <b>Yaratuvchi:</b> {escape(creator.full_name)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>Natijalarni ko‘rish:</b> /natijablock_{test.id}\n"
        f"🛑 <b>Testni yakunlash:</b> /stop_block_{test.id}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"📢 Quyidagi tayyor izohni o‘quvchilaringizga yuborishingiz mumkin 👇👇👇"
    ))
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Testga o'tish", url=bot_link()))
    user_send_message(creator.telegram_id, f"""<b>🧠 BLOK TEST BOSHLANDI!</b>

👤 <b>Test muallifi:</b>
<a href='tg://user?id={creator.telegram_id}'>{escape(creator.full_name)}</a>

📚 <b>Fanlar:</b> {subjects_str}
🆔 <b>Test kodi:</b> <code>{test.id}</code>

━━━━━━━━━━━━━━━━━━━━━━

📢 <b>Javoblaringizni yuboring:</b>
➡️ <a href="{bot_link()}">@{settings.TELEGRAM_BOT_USERNAME}</a>

🚀 Omad tilaymiz! To‘g‘ri javoblaringiz ko‘p bo‘lsin! 💪
""", markup=markup)


def submit_block_test(test, user, user_answers, request=None):
    """DTM javoblarini eski tizim qoidalari bilan baholaydi va saqlaydi."""
    if not test.is_active:
        raise SubmissionError("Ushbu test yakunlangan yoki faol emas")
    if not user_answers:
        raise SubmissionError("Javoblar yuborilmadi")

    total_score, correct_count, detailed = test.calculate_score(user_answers)
    result, _ = BlockTestResult.objects.update_or_create(
        user=user, test=test,
        defaults={"user_answers": user_answers, "total_score": total_score,
                  "correct_answers": correct_count, "detailed_results": detailed},
    )

    lines = [
        f"🏁 <b>Blok Test Natijasi</b>\n\n🆔 <b>Test ID:</b> {test.id}\n"
        f"👤 <b>Foydalanuvchi:</b> {escape(user.full_name)}\n\n"
        f"📊 <b>Umumiy Natija:</b>\n✅ To'g'ri javoblar: {correct_count}\n⭐️ Ball: {total_score}\n\n"
        "<b>Fanlar bo'yicha:</b>\n\n"
    ]
    for key, data in detailed.items():
        lines.append(f"📚 <b>{escape(dtm_subject_name(key))}</b>\n   ✅ To'g'ri: {data['correct_answers']}\n"
                     f"   ⭐️ Ball: {data['score']}\n\n")
    lines.append(f"📅 Vaqt: {timezone.localtime():%Y-%m-%d %H:%M:%S}")
    user_send_message(user.telegram_id, "".join(lines))

    log_to_telegram("results", (
        f"📝 <b>Blok Test Topshirildi</b>\n🆔 Test ID: {test.id}\n📊 Ball: {total_score}\n✅ To'g'ri: {correct_count}"
    ), request=request, user=user)
    return total_score, correct_count, detailed, result


def certificate_value(raw, max_score):
    """Sertifikat balini tekshiradi: bo'sh -> None, noto'g'ri -> SubmissionError."""
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise SubmissionError("Sertifikat bali raqam bo'lishi kerak.")
    if not 0 < value <= max_score:
        raise SubmissionError(f"Sertifikat bali 0 dan katta va {max_score:g} dan oshmasligi kerak.")
    return value


MANDATORY_CERTIFICATE_SCORE = round(MANDATORY_POINT * 10, 1)


# ---------------------------------------------------------------------------
# Kitob testlari
# ---------------------------------------------------------------------------

GRADE_MESSAGES = {
    "A+": "🎉 Zo‘r! Siz mukammal natija qo‘lga kiritdingiz!",
    "A": "👍 Zo‘r! Siz yaxshi natija oldingiz.",
    "B+": "🙂 Yaxshi! Siz biroz yaxshilashingiz mumkin.",
    "B": "🙂 Qoniqarli. Bir oz ko‘proq e’tibor bering.",
    "C+": "😐 Qoniqarli, lekin yaxshilash mumkin.",
    "C": "😕 Qoniqarsiz, yana urinib ko‘ring.",
    "F": "❌ Qoniqarsiz, qayta urinib ko‘ring!",
}


def notify_booktest_created(test):
    caption = (
        f"✅ <b>Kitob Test muvaffaqiyatli yaratildi!</b>\n\n"
        f"📚 <b>Test nomi:</b> {escape(test.title)}\n"
        f"📖 <b>Fan:</b> {escape(test.subject.name)}\n"
        f"📋 <b>Savollar soni:</b> {test.questions_count}\n"
        f"🆔 <b>Kodi:</b> <code>{test.slug}</code>\n\n"
        f"👤 <b>Yaratuvchi:</b> {escape(test.creator.full_name)}\n\n"
        f"🔗 <b>Testga havola:</b> {test.qr_link()}\n"
        f"📊 <b>Natijalar:</b> /kitobnatija_{test.slug}"
    )
    try:
        if test.qr_code:
            with test.qr_code.open("rb") as photo:
                bot.send_photo(chat_id=test.creator.telegram_id, photo=photo, caption=caption, parse_mode="HTML")
            return
    except Exception:
        pass
    user_send_message(test.creator.telegram_id, caption)


def submit_booktest(test, user, user_answers, extra_ball=0, request=None):
    """Kitob testi javoblarini tekshiradi, natijani saqlaydi va foydalanuvchiga yuboradi."""
    if not isinstance(user_answers, dict) or not user_answers:
        raise SubmissionError("Kamida bitta savolga javob bering.")
    try:
        extra_ball = float(extra_ball or 0)
    except (TypeError, ValueError):
        raise SubmissionError("Qo'shimcha ball raqam bo'lishi kerak.")
    if extra_ball < 0:
        raise SubmissionError("Qo'shimcha ball manfiy bo'lishi mumkin emas.")

    with transaction.atomic():
        test = BookTest.objects.select_for_update().get(pk=test.pk)
        result = test.check_answer(user_answers, user=user, extra_ball=extra_ball)
        if not result.get("success"):
            raise SubmissionError(f"Javoblarni tekshirishda xatolik: {result.get('error')}")
        grade = test.get_grade(result["score"])
        record, _ = BookTestResult.objects.update_or_create(
            user=user, test=test,
            defaults={
                "user_answers": result["answers"], "submitted_answers": user_answers,
                "correct_answers": result["correct"], "total_questions": result["total"],
                "extra_ball": result["extra_ball"], "score": result["score"],
                "percentage": result["percentage"], "grade": grade,
            },
        )

    user_send_message(user.telegram_id, (
        f"📝 Test natijasi\n\n"
        f"📚 Test: {escape(test.title)}\n"
        f"✅ To‘g‘ri: {result['correct']} / {result['total']}\n"
        f"📊 Foiz: {result['percentage']}%\n"
        f"🎯 Ball: {result['score']}\n"
        f"🏅 Daraja: {grade}\n\n"
        f"{GRADE_MESSAGES.get(grade, '')}"
    ))
    log_to_telegram("results", (
        f"📚 <b>Kitob Test ishlandi</b>\n📝 Test: {escape(test.title)}\n"
        f"📊 Natija: {result['correct']}/{result['total']} ({result['percentage']}%)\n🆔 Kod: {test.slug}"
    ), request=request, user=user)
    return result, grade, record
