"""Server xatolarini ko'rish va tozalash.

    python manage.py errors                 # oxirgi xatolar (traceback bilan)
    python manage.py errors --clear         # hammasini o'chirish (tuzatilgandan keyin)
    python manage.py errors --clear a1b2c3  # faqat shu fingerprint(lar)ni o'chirish
"""
from django.core.management.base import BaseCommand

from main.errorlog import clear_errors, render_text


class Command(BaseCommand):
    help = "Server xatolarini ko'rsatadi (logs/errors.json)"

    def add_arguments(self, parser):
        parser.add_argument("--clear", nargs="*", metavar="FINGERPRINT", help="Xatolarni ro'yxatdan o'chirish")
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        if options["clear"] is not None:
            removed = clear_errors(options["clear"] or None)
            self.stdout.write(f"{removed} ta xato o'chirildi.")
            return
        self.stdout.write(render_text(limit=options["limit"]))
