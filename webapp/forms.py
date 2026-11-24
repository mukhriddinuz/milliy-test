import json
import re

from django import forms
from django.utils import timezone

from main.models import Subject
from main.regions import REGIONS

CHOICES_4 = ["A", "B", "C", "D"]
CHOICES_6 = ["A", "B", "C", "D", "E", "F"]

# Milliy sertifikat test tuzilishi
SINGLE_4 = range(1, 33)        # 1–32: A–D
SINGLE_6 = range(33, 36)       # 33–35: A–F
WRITTEN_START = 36             # 36+: yozma (ko'p qismli) savollar
WRITTEN_BLOCKS = 10
WRITTEN_MAX_PARTS = 45


def options_for(number):
    return CHOICES_4 if number <= 32 else CHOICES_6


class RegisterForm(forms.Form):
    name = forms.CharField(label="Ism", max_length=100)
    surname = forms.CharField(label="Familiya", max_length=100)
    father_name = forms.CharField(label="Sharif", max_length=100)
    phone = forms.RegexField(
        label="Telefon raqam", regex=r"^\+998\d{9}$",
        error_messages={"invalid": "Telefon raqami to'liq kiritilishi kerak (+998XXXXXXXXX)"},
    )
    region = forms.ChoiceField(label="Viloyat", choices=[("", "Viloyatni tanlang")] + [(r, r) for r in REGIONS])
    district = forms.CharField(label="Tuman", max_length=100)

    def clean_phone(self):
        return re.sub(r"[^\d+]", "", self.cleaned_data["phone"])

    def clean(self):
        data = super().clean()
        region, district = data.get("region"), data.get("district")
        if region and district and district not in REGIONS.get(region, []):
            self.add_error("district", "Tumanni ro'yxatdan tanlang")
        for f in ("name", "surname", "father_name"):
            if f in data:
                data[f] = data[f].strip()
        return data


def parse_choice_answers(post, numbers, prefix="q_", options=None, required=True):
    """Radio javoblarni o'qiydi: ({"1": "A", ...}, [javobsiz savollar])."""
    answers, missing = {}, []
    for n in numbers:
        allowed = options or options_for(n)
        value = (post.get(f"{prefix}{n}") or "").strip().upper()
        if value in allowed:
            answers[str(n)] = value
        elif required:
            missing.append(n)
    return answers, missing


def parse_local_datetime(value):
    """<input type="datetime-local"> qiymatini (Toshkent vaqti) aware datetime'ga aylantiradi."""
    try:
        return forms.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"]).clean(value)
    except forms.ValidationError:
        return None


def parse_sheet_answers(d, errors):
    """Milliy sertifikat tuzilishidagi javoblar: 1–35 radio (q_N) va yozma bloklar (written JSON).

    Qaytaradi: (answers, yozma bloklar soni)
    """
    answers, missing = parse_choice_answers(d, list(SINGLE_4) + list(SINGLE_6))
    if missing:
        errors.append(f"Quyidagi savollarga javob belgilanmagan: {', '.join(map(str, missing))}.")
    try:
        written = json.loads(d.get("written") or "[]")
        assert isinstance(written, list) and len(written) <= WRITTEN_BLOCKS
        assert all(isinstance(b, list) and 1 <= len(b) <= WRITTEN_MAX_PARTS for b in written)
        written = [[str(v).strip().upper() for v in block] for block in written]
    except (ValueError, AssertionError):
        written = []
        errors.append("Yozma javoblar noto'g'ri formatda yuborildi.")
    if any(not v for block in written for v in block):
        errors.append("Yozma savollarning barcha qismlarini to'ldiring.")
    for i, block in enumerate(written):
        answers[str(WRITTEN_START + i)] = {str(j + 1): v for j, v in enumerate(block)}
    return answers, len(written)


class NationalTestForm:
    """Milliy sertifikat testini yaratish formasi (POST ma'lumotlarini tekshiradi)."""

    def __init__(self, data=None):
        self.data = data
        self.errors = []
        self.cleaned = {}

    def is_valid(self):
        d = self.data
        subject = Subject.objects.filter(pk=d.get("subject") or 0, is_active=True).first()
        if subject is None:
            self.errors.append("Fanni tanlang.")

        answers, _ = parse_sheet_answers(d, self.errors)

        is_public = d.get("is_public") == "on"
        channel, start_time = None, None
        if is_public:
            channel = (d.get("channel_username") or "").strip()
            if not channel.startswith("@"):
                channel = "@" + channel.lstrip("@")
            if not re.fullmatch(r"@[A-Za-z0-9_]{1,64}", channel):
                self.errors.append("Kanal username'ini to'g'ri kiriting (masalan, @kanal_nomi).")
            start_time = parse_local_datetime(d.get("start_time") or "")
            if start_time is None:
                self.errors.append("Test o'tkaziladigan vaqtni tanlang.")
            elif start_time <= timezone.now():
                self.errors.append("Test vaqti hozirgi vaqtdan keyin bo'lishi kerak.")

        self.cleaned = {
            "subject": subject, "answers": answers, "is_public": is_public,
            "channel_username": channel, "start_time": start_time,
        }
        return not self.errors


class BookTestForm:
    """Kitob testini yaratish: Milliy sertifikat tuzilishi + har bir savol bali."""

    def __init__(self, data=None):
        self.data = data
        self.errors = []
        self.cleaned = {}

    def is_valid(self):
        d = self.data
        subject = Subject.objects.filter(pk=d.get("subject") or 0).first()
        if subject is None:
            self.errors.append("Fanni tanlang.")
        title = (d.get("title") or "").strip()
        if not title or len(title) > 200:
            self.errors.append("Test nomini kiriting (200 belgigacha).")

        answers, _ = parse_sheet_answers(d, self.errors)
        try:
            scores = [float(x) for x in json.loads(d.get("scores") or "[]")]
            assert len(scores) == len(answers) and all(0 < x <= 100 for x in scores)
        except (ValueError, TypeError, AssertionError):
            scores = []
            self.errors.append("Har bir savol uchun 0 dan katta ball kiriting.")

        self.cleaned = {
            "subject": subject, "title": title, "answers": answers,
            "scores": [int(x) if x == int(x) else x for x in scores],
            "book_test": d.get("book_test") == "on", "extra_ball": d.get("extra_ball") == "on",
        }
        return not self.errors


class DtmTestForm:
    """DTM (blok) testini yaratish: 2 ta asosiy fan (30 tadan) + 3 ta majburiy fan (10 tadan)."""

    def __init__(self, data=None):
        self.data = data
        self.errors = []
        self.cleaned = {}

    def is_valid(self):
        from main.services import DTM_MANDATORY_BLOCKS, DTM_OPTIONAL_SUBJECTS

        d = self.data
        valid = dict(DTM_OPTIONAL_SUBJECTS)
        main1, main2 = d.get("main_subject_1"), d.get("main_subject_2")
        if main1 not in valid or main2 not in valid:
            self.errors.append("Ikkala asosiy fanni tanlang.")
        elif main1 == main2:
            self.errors.append("Ikkita asosiy fan bir xil bo'lishi mumkin emas!")

        answers, incomplete = {}, False
        blocks = [("main_1", 30), ("main_2", 30)] + [(key, len(numbers)) for key, numbers in DTM_MANDATORY_BLOCKS]
        for key, count in blocks:
            answers[key], missing = parse_choice_answers(d, range(1, count + 1), prefix=f"{key}_", options=CHOICES_4)
            incomplete = incomplete or bool(missing)
        if incomplete:
            self.errors.append("Barcha bloklardagi savollarga to'g'ri javobni belgilang.")

        self.cleaned = {"main_subject_1": main1, "main_subject_2": main2, "answers": answers}
        return not self.errors
