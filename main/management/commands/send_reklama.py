"""Navbatdagi reklamani faol foydalanuvchilarga bir partiya (100 ta) qilib yuboradi.

Serverda cron orqali har daqiqada ishga tushiriladi:
    * * * * * cd /path/to/project && python manage.py send_reklama

Har ishga tushganda keyingi 100 kishiga yuboradi; hammaga yetganda reklama "completed" bo'ladi.
--loop bilan barcha partiyalarni ketma-ket yuboradi (cron bo'lmasa qo'lda ishlatish uchun).
"""
import time

import telebot
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from main.models import Reklama, TelegramUser
from main.reklama import send_reklama

BATCH_SIZE = 100


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
        bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN or "0:not-configured", parse_mode="HTML")
        while self.send_batch(bot, options["delay"]) and options["loop"]:
            pass

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
            reklama = (
                Reklama.objects.select_for_update()
                .filter(status__in=["ready", "pending"])
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

        sent_ids = reklama.sending_users.values_list("id", flat=True)
        users = list(TelegramUser.objects.filter(is_active=True).exclude(id__in=sent_ids).order_by("id")[:BATCH_SIZE])

        if not users:
            reklama.status = "completed"
            reklama.completed_at = timezone.now()
            reklama.save(update_fields=["status", "completed_at"])
            self.notify(bot, reklama, finished=True)
            return False

        for user in users:
            reklama.refresh_from_db(fields=["status"])
            if reklama.status == "cancelled":
                self.stdout.write("Reklama bekor qilindi.")
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

        reklama.status = "pending"
        reklama.save(update_fields=["status"])
        self.notify(bot, reklama)
        return True
