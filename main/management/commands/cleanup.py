"""Bazani ixcham saqlash (oyiga bir marta cron bilan yoki qo'lda):

    python manage.py cleanup            # keraksiz qatorlarni o'chirish
    python manage.py cleanup --vacuum   # + SQLite faylini siqish (bir necha soniya bazani band qiladi)

Foydalanuvchilar, testlar va natijalarga TEGMAYDI. Faqat:
  * tugagan/bekor qilingan reklamalarning "kimga yuborildi" ro'yxati (statistika sonlari qoladi);
  * eski sessiya qatorlari (sessiyalar endi cookie'da, jadval kerak emas);
  * 180 kundan eski admin panel amallari jurnali.
"""
from datetime import timedelta

from django.contrib.admin.models import LogEntry
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from main.models import Reklama


class Command(BaseCommand):
    help = "Bazadagi keraksiz qatorlarni o'chiradi (foydalanuvchi ma'lumotlariga tegmaydi)"

    def add_arguments(self, parser):
        parser.add_argument("--vacuum", action="store_true", help="SQLite faylini siqish")

    def handle(self, *args, **options):
        through = Reklama.sending_users.through
        finished = Reklama.objects.exclude(status__in=["draft", "ready", "pending", "sending"])
        n_sent, _ = through.objects.filter(reklama__in=finished).delete()
        n_sessions, _ = Session.objects.all().delete()
        n_log, _ = LogEntry.objects.filter(action_time__lt=timezone.now() - timedelta(days=180)).delete()
        self.stdout.write(f"O'chirildi: reklama qatorlari {n_sent}, sessiyalar {n_sessions}, admin jurnali {n_log}")

        if options["vacuum"] and connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("VACUUM")
            self.stdout.write("Baza fayli siqildi (VACUUM).")
