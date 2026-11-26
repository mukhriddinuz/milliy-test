"""Navbatdagi reklamani faol foydalanuvchilarga bir partiya (100 ta) qilib yuboradi.

Serverda cron orqali har daqiqada ishga tushiriladi:
    * * * * * cd /path/to/project && python manage.py send_reklama

Har ishga tushganda keyingi 100 kishiga yuboradi; hammaga yetganda reklama "completed" bo'ladi.
--loop bilan barcha partiyalarni ketma-ket yuboradi (cron bo'lmasa qo'lda ishlatish uchun).
"""
import logging
import time

import telebot
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from main.models import Reklama, TelegramUser
from main.reklama import send_reklama
from main.state import acquire_lock, refresh_lock, release_lock

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
LOCK_NAME = "send_reklama"
# Qulf shu vaqtdan keyin o'z-o'zidan ochiladi (jarayon o'lib qolgan bo'lsa ham reklama to'xtab qolmaydi)
LOCK_TIMEOUT = 15 * 60


def progress_text(reklama, finished=False):
    head = "Reklama yakunlandi." if finished else "Reklama yuborilmoqda."
    left = max(reklama.total_users - reklama.sent_count - reklama.failed_count, 0)
    return (
        f"{head} Jami {reklama.total_users} ta foydalanuvchi.\n\n"
        f"Yuborildi: {reklama.sent_count}\nXatolik: {reklama.failed_count}\nQolgan: {left}"
    )


class Command(BaseCommand):
    help = "Navbatdagi reklamani 100 tadan foydalanuvchiga yuboradi"

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Reklama tugaguncha barcha partiyalarni yuborish")
        parser.add_argument("--delay", type=float, default=0.5, help="Har bir xabar orasidagi pauza (soniya)")

    def handle(self, *args, **options):
        # Navbat bo'sh bo'lsa (deyarli har doim) — bitta yengil so'rov va darhol chiqish
        if not Reklama.objects.filter(status__in=["ready", "pending", "sending"]).exists():
            return
        # Cron har daqiqada ishga tushiradi, partiya esa 1 daqiqadan uzoq davom etishi mumkin.
        # Qulf bo'lmasa, ikki jarayon bir xil foydalanuvchilarga ikki marta yuborib yuboradi.
        if not acquire_lock(LOCK_NAME, LOCK_TIMEOUT):
            self.stdout.write("Boshqa send_reklama jarayoni ishlayapti.")
            return
        try:
            bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN or "0:not-configured", parse_mode="HTML")
            while self.send_batch(bot, options["delay"]) and options["loop"]:
                refresh_lock(LOCK_NAME, LOCK_TIMEOUT)
        except Exception:
            logger.exception("send_reklama buyrug'ida xato")  # cron xatosi ham xatolar jurnaliga tushadi
            raise
        finally:
            release_lock(LOCK_NAME)

    def notify(self, bot, reklama, finished=False):
        text = progress_text(reklama, finished)
        try:
            if reklama.stats_message_id:
                bot.edit_message_text(chat_id=reklama.admin_user_id, message_id=reklama.stats_message_id, text=text)
            else:
                msg = bot.send_message(chat_id=reklama.admin_user_id, text=text)
                reklama.stats_message_id = msg.message_id
                reklama.save(update_fields=["stats_message_id"])
        except Exception as e:
            self.stdout.write(f"Statistika xabarini yangilashda xatolik: {e}")

    def send_batch(self, bot, delay):
        """Bitta partiya yuboradi. Yana yuboriladigan narsa qolgan bo'lsa True."""
        with transaction.atomic():
            # "sending" — oldingi jarayon xato bilan to'xtab qolgan (qulf bizda, demak boshqasi ishlamayapti)
            reklama = (
                Reklama.objects.select_for_update()
                .filter(status__in=["ready", "pending", "sending"])
                .order_by("created_at")
                .first()
            )
            if not reklama:
                return False
            if reklama.status == "ready":
                reklama.started_at = timezone.now()
                reklama.total_users = TelegramUser.objects.filter(is_active=True).count()
            reklama.status = "sending"
            reklama.save(update_fields=["status", "started_at", "total_users"])

        self.notify(bot, reklama)

        users = list(
            TelegramUser.objects.filter(is_active=True)
            .exclude(sending_messages=reklama)
            .order_by("id")[:BATCH_SIZE]
        )

        if not users:
            reklama.status = "completed"
            reklama.completed_at = timezone.now()
            reklama.save(update_fields=["status", "completed_at"])
            # Kimga yuborilgani faqat yuborish paytida kerak; tugagach bu qatorlar (foydalanuvchilar
            # soni × reklamalar soni) bazani behuda shishiradi. Statistika (sent/failed) saqlanib qoladi.
            reklama.sending_users.clear()
            self.notify(bot, reklama, finished=True)
            return False

        for user in users:
            reklama.refresh_from_db(fields=["status"])
            if reklama.status == "cancelled":
                self.stdout.write("Reklama bekor qilindi.")
                reklama.sending_users.clear()
                self.notify(bot, reklama, finished=True)
                return False
            ok = send_reklama(bot, reklama, user)
            reklama.sending_users.add(user)
            if ok:
                reklama.sent_count += 1
            else:
                reklama.failed_count += 1
            reklama.save(update_fields=["sent_count", "failed_count"])
            time.sleep(delay)

        # Admin shu orada bekor qilgan bo'lsa, "cancelled" holatini ustidan yozib yubormaymiz
        Reklama.objects.filter(pk=reklama.pk, status="sending").update(status="pending")
        self.notify(bot, reklama)
        return True
