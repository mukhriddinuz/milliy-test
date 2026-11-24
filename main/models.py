from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.core.files.base import ContentFile
from django.db import models


class TelegramUser(models.Model):
    # Telegram ma'lumotlari
    telegram_id = models.BigIntegerField(unique=True, verbose_name="Telegram ID")
    username = models.CharField(max_length=50, blank=True, null=True, verbose_name="Username")
    
    # Shaxsiy ma'lumotlar
    surname = models.CharField(max_length=100, verbose_name="Familiya")
    name = models.CharField(max_length=100, verbose_name="Ism")
    father_name = models.CharField(max_length=100, blank=True, null=True, verbose_name="Sharif")
    
    # Telefon raqami validatori
    phone_validator = RegexValidator(
        regex=r'^\+998\d{9}$',
        message="Telefon raqami +998XXXXXXXXX formatida bo'lishi kerak"
    )
    phone = models.CharField(
        max_length=20, 
        validators=[phone_validator], 
        verbose_name="Telefon raqami"
    )
    
    region = models.CharField(
        max_length=20, 
        verbose_name="Viloyat"
    )
    district = models.CharField(max_length=100, verbose_name="Tuman")
    is_admin = models.BooleanField(default=False, verbose_name="Admin")
    # Moliyaviy ma'lumotlar
    balance = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        verbose_name="Balans (so'm)"
    )
    
    # Qo'shimcha ma'lumotlar
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    is_banned = models.BooleanField(default=False, verbose_name="Bloklangan")
    
    # Sana ma'lumotlari
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ro'yxatdan o'tgan sana")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="O'zgartirilgan sana")


    class Meta:
        verbose_name = "Telegram Foydalanuvchi"
        verbose_name_plural = "Telegram Foydalanuvchilar"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} {self.surname}"
    
    @property
    def full_name(self):
        """To'liq ismni qaytaradi"""
        return f"{self.surname} {self.name}"
    
    @property
    def balans_formatted(self):
        """Formatlangan balansni qaytaradi"""
        return f"{self.balance:,.2f} so'm"
    
    
class RequiredChannel(models.Model):
    channel_username = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        verbose_name="Kanal username",
        help_text="Kanal nomi @ belgisi bilan boshlanishi kerak"
    )
    channel_id = models.BigIntegerField(
        unique=True,
        verbose_name="Kanal ID",
        help_text="Telegram kanalining raqamli ID si"
    )
    invite_link = models.URLField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Invite link",
        help_text="Username bo‘lmagan kanallar uchun to‘liq t.me havolasi"
    )
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Majburiy Kanal"
        verbose_name_plural = "Majburiy Kanallar"
        ordering = ['channel_username']

    def __str__(self):
        return f"{self.channel_username or self.channel_id} ({'Faol' if self.is_active else 'Nofaol'})"

    def get_link(self):
        """ Kanalga to‘g‘ridan-to‘g‘ri kirish havolasi """
        if self.channel_username:
            return f"https://t.me/{self.channel_username.lstrip('@')}"
        elif self.invite_link:
            return self.invite_link
        return None

    

class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Fan nomi")
    description = models.TextField(blank=True, null=True, verbose_name="Tavsif")
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    
    # Sana ma'lumotlari
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan sana")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="O'zgartirilgan sana")

    class Meta:
        verbose_name = "Fan"
        verbose_name_plural = "Fanlar"
        ordering = ['name']

    def __str__(self):
        return self.name

class Test(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="tests", verbose_name="Fan")
    creator = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name="created_tests", verbose_name="Yaratuvchi")
    
    # Test ma'lumotlari
    title = models.CharField(max_length=200, verbose_name="Test nomi")
    questions_count = models.PositiveIntegerField(verbose_name="Savollar soni")
    
    # Test sozlamalari
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    is_public = models.BooleanField(default=False, verbose_name="Hamma uchun ochiqmi")
    channel_username = models.CharField(max_length=100, blank=True, null=True, verbose_name="Kanal username")
    start_time = models.DateTimeField(verbose_name="Test boshlanish vaqti", null=True, blank=True)
    
    # Javoblar va natijalar
    answers = models.JSONField(verbose_name="To'g'ri javoblar", default=dict)
    correct_answers = models.JSONField(verbose_name="Javoblar ro'yxati", default=list,null=True, blank=True)
    scores = models.JSONField(verbose_name="Savol ballari", default=list, blank=True)
    extra_ball = models.BooleanField(default=False, verbose_name="Qo'shimcha bal maydoni")
    # Sana ma'lumotlari
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan sana")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="O'zgartirilgan sana")

    class Meta:
        verbose_name = "Test"
        verbose_name_plural = "Testlar"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.id} {self.title} - {self.subject.name}"

    def clean(self):
        """Ma'lumotlarni tekshirish"""
        # questions_count save() da answers'dan hisoblanadi, shuning uchun answers'ni tekshiramiz
        if not isinstance(self.answers, dict) or not self.answers:
            raise ValidationError({"answers": "Kamida bitta savol javobi kiritilishi kerak, masalan: {\"1\": \"A\"}"})
        
        

    def save(self, *args, **kwargs):
        self.questions_count = len(self.answers) if self.answers else 0

        if not self.correct_answers or len(self.correct_answers) != self.questions_count:
            self.correct_answers = [0 for _ in range(self.questions_count)]

        super().save(*args, **kwargs)
    

    def check_answer(self, user_answers: dict, user=None):
        """
        Foydalanuvchi javoblarini tekshirish va statistikani yangilash.
        Agar foydalanuvchi qayta topshirsa, avvalgi natija statistikadan olib tashlanadi.
        """
        try:
            correct = 0
            answers = []
            total = len(self.answers) if self.answers else 0

            # --- correct_answers tayyorlash ---
            if not self.correct_answers or len(self.correct_answers) != total:
                self.correct_answers = [0 for _ in range(total)]

            # --- agar user mavjud bo'lsa, eski natijasini topamiz ---
            old_result = None
            if user:
                old_result = self.results.filter(user=user).first()
                if old_result:
                    # eski natijani hisobdan olib tashlaymiz
                    for i, val in enumerate(old_result.user_answers):
                        if i < len(self.correct_answers) and val == 1:
                            self.correct_answers[i] = max(0, self.correct_answers[i] - 1)

            # --- yangi javoblarni tekshiramiz ---
            for q_id, right_answer in (self.answers or {}).items():
                q_index = int(q_id) - 1
                user_answer = user_answers.get(q_id)
                is_correct = False

                # oddiy string javob
                if isinstance(right_answer, str):
                    is_correct = str(user_answer).strip().lower() == right_answer.strip().lower()
                # dict javob
                elif isinstance(right_answer, dict):
                    is_correct = isinstance(user_answer, dict) and user_answer == right_answer
                # list javob
                elif isinstance(right_answer, list):
                    if isinstance(user_answer, str):
                        user_answer = [user_answer]
                    is_correct = (
                        isinstance(user_answer, list)
                        and sorted(map(str, user_answer)) == sorted(map(str, right_answer))
                    )

                if is_correct:
                    correct += 1
                    answers.append(1)
                    if 0 <= q_index < len(self.correct_answers):
                        self.correct_answers[q_index] += 1
                else:
                    answers.append(0)

            percentage = round(correct / total * 100, 2) if total > 0 else 0.0

            # testni yangilaymiz
            self.save(update_fields=["correct_answers", "updated_at"])

            return {
                "correct": correct,
                "total": total,
                "percentage": percentage,
                "answers": answers
            }

        except Exception as e:
            return {"error": str(e)}



class TestResult(models.Model):
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name="test_results", verbose_name="Foydalanuvchi")
    test = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="results", verbose_name="Test")
    
    # Natija ma'lumotlari
    correct_answers = models.PositiveIntegerField(verbose_name="To'g'ri javoblar soni")
    total_questions = models.PositiveIntegerField(verbose_name="Umumiy savollar soni")
    percentage = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Foiz")
    total_ball = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="Umumiy ball", default=0)
    
    # Foydalanuvchi yuborgan javoblar
    user_answers = models.JSONField(verbose_name="Foydalanuvchi javoblari", default=list)
    
    # Savol ballari (Rasch modeli asosida)
    question_weights = models.JSONField(verbose_name="Savol ballari", default=list, blank=True)
    earned_points = models.JSONField(verbose_name="Olingan ballar", default=list, blank=True)
    
    # Sana ma'lumotlari
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="Topshirilgan sana")

    class Meta:
        verbose_name = "Test Natija"
        verbose_name_plural = "Test Natijalar"
        ordering = ['-submitted_at']
        unique_together = ['user', 'test']  # Har bir foydalanuvchi testga bir marta javob beradi

    def __str__(self):
        return f"{self.user} - {self.test.title} - {self.total_ball} ball"

    @property
    def is_passed(self):
        """Testdan o'tgan yoki o'tmaganligini tekshiradi (50 ball dan yuqori bo'lsa o'tgan)"""
        return float(self.total_ball) >= 50

    def get_grade(self):
        """
        Ballarni baholash tizimi (100 ball asosida)
        """
        ball = float(self.total_ball)
        
        if ball >= 70:
            return "A+", "A'lo"
        elif ball >= 65:
            return "A", "Yaxshi"
        elif ball >= 60:
            return "B+", "Yaxshi"
        elif ball >= 55:
            return "B", "Qoniqarli"
        elif ball >= 50:
            return "C+", "Qoniqarli"
        elif ball >= 46:
            return "C", "Qoniqarsiz"
        else:
            return "F", "Qoniqarsiz"

    def get_detailed_results(self):
        """
        Batafsil natijalarni olish
        """
        grade, description = self.get_grade()
        
        return {
            'user': self.user.full_name,
            'test': self.test.title,
            'correct_answers': self.correct_answers,
            'total_questions': self.total_questions,
            'total_ball': float(self.total_ball),
            'percentage': float(self.percentage),
            'grade': grade,
            'description': description,
            'is_passed': self.is_passed,
            'submitted_at': self.submitted_at,
            'question_weights': self.question_weights,
            'earned_points': self.earned_points
        }


class Instructions(models.Model):
    content = models.TextField(verbose_name="Ko'rsatmalar matni")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan sana")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="O'zgartirilgan sana")

    class Meta:
        verbose_name = "Ko'rsatma"
        verbose_name_plural = "Ko'rsatmalar"
        ordering = ['-created_at']

    def __str__(self):
        return f"Ko'rsatma {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"

# ---------------------------------------------------------------------------
# Reklama (admin /reklama orqali yaratadi, `manage.py send_reklama` cron bilan yuboradi)
# ---------------------------------------------------------------------------

class Reklama(models.Model):
    TYPE = (
        ('text', 'Matn'),
        ('image', 'Rasm'),
        ('video', 'Video'),
        ('document', 'Fayl'),
        ('audio', 'Audio'),
        ('voice', 'Ovoz'),
        ('forward', 'Forward')
    )
    STATUS = (
        ('draft', 'Tasdiqlanmagan'),
        ('pending', 'Kutilmoqda'),
        ('sending', 'Yuborilmoqda'),
        ('ready', 'Tayyor'),
        ('sent', 'Yuborildi'),
        ('failed', 'Yuborilishi muvaffaqiyatli bajarilmadi'),
        ('cancelled', 'Yuborilishi bekor qilindi'),
        ('completed', 'Yuborilishi tugatildi'),
        ('not_sent_in_full', 'Yuborilishi tugallanmadi'),
        ('error_in_message', 'Xabardagi xatolik'),
    )

    admin_user_id = models.BigIntegerField(verbose_name="Admin ID")
    message_type = models.CharField(max_length=20, choices=TYPE, verbose_name="Xabar turi")

    # Matn ma'lumotlari
    text = models.TextField(null=True, blank=True, verbose_name="Matn")
    parsed_text = models.TextField(null=True, blank=True, verbose_name="Parse qilingan matn")
    buttons_json = models.JSONField(null=True, blank=True, verbose_name="Tugmalar (JSON)")

    # Media ma'lumotlari
    file_id = models.CharField(max_length=255, null=True, blank=True, verbose_name="File ID")

    # copy_message uchun manba xabar
    source_message_id = models.BigIntegerField(null=True, blank=True, verbose_name="Manba xabar ID")
    source_chat_id = models.BigIntegerField(null=True, blank=True, verbose_name="Manba chat ID")

    # Forward xabar uchun (eski)
    forward_from_chat_id = models.BigIntegerField(null=True, blank=True, verbose_name="Forward from chat")
    forward_message_id = models.BigIntegerField(null=True, blank=True, verbose_name="Forward message ID")

    # Statistika
    status = models.CharField(max_length=20, choices=STATUS, default='pending', verbose_name="Holat")
    total_users = models.IntegerField(default=0, verbose_name="Jami foydalanuvchilar")
    sent_count = models.IntegerField(default=0, verbose_name="Yuborildi")
    failed_count = models.IntegerField(default=0, verbose_name="Xatolik")

    sending_users = models.ManyToManyField(TelegramUser, related_name='sending_messages')
    stats_message_id = models.BigIntegerField(null=True, blank=True, verbose_name="Statistika xabarni ID")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan vaqt")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="Boshlangan vaqt")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Tugagan vaqt")

    class Meta:
        verbose_name = "Reklama"
        verbose_name_plural = "Reklamalar"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Reklama #{self.pk} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if self.text:
            from .utils import parse_reklama_text

            self.parsed_text, self.buttons_json = parse_reklama_text(self.text)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Kitob testlari (QR kod orqali: https://t.me/<bot>?startapp=test_<slug>)
# ---------------------------------------------------------------------------

def compare_answers(user_answer, right_answer):
    """Bitta savol javobini solishtiradi (matn, ko'p qismli dict yoki ro'yxat)."""
    if isinstance(right_answer, str):
        return str(user_answer).strip().lower() == right_answer.strip().lower()
    if isinstance(right_answer, dict):
        if not isinstance(user_answer, dict):
            return False
        norm = lambda d: {str(k): str(v).strip().lower() for k, v in d.items()}
        return norm(user_answer) == norm(right_answer)
    if isinstance(right_answer, list):
        if isinstance(user_answer, str):
            user_answer = [user_answer]
        return isinstance(user_answer, list) and sorted(map(str, user_answer)) == sorted(map(str, right_answer))
    return False


def booktest_grade(total_ball):
    """Milliy sertifikat darajasi (faqat harf)."""
    for limit, grade in ((70, "A+"), (65, "A"), (60, "B+"), (55, "B"), (50, "C+"), (46, "C")):
        if total_ball >= limit:
            return grade
    return "F"


class BookTest(models.Model):
    """Kitob testlari modeli"""

    subject = models.ForeignKey('Subject', on_delete=models.CASCADE, related_name="booktests", verbose_name="Fan")
    creator = models.ForeignKey(
        'TelegramUser', on_delete=models.CASCADE, related_name="created_booktests", verbose_name="Yaratuvchi"
    )
    book_test = models.BooleanField(default=False, verbose_name="Kitobga chiqarilganmi")

    title = models.CharField(max_length=200, verbose_name="Test nomi")
    slug = models.SlugField(max_length=255, unique=True, blank=True, null=True, verbose_name="Slug")
    questions_count = models.PositiveIntegerField(default=0, verbose_name="Savollar soni")

    # {"1": "A", "36": {"1": "JAVOB"}, ...}
    answers = models.JSONField(
        verbose_name="To'g'ri javoblar", default=dict,
        help_text="Format: {'1': 'A', '2': ['B', 'C'], '3': {'key': 'value'}}"
    )
    # Har bir savol uchun ball: [2, 2, 1.5, ...]
    scores = models.JSONField(
        verbose_name="Savol ballari", default=list, blank=True,
        help_text="Har bir savol uchun ball. Agar bo'sh bo'lsa, barcha savollar 1 ball"
    )
    correct_answers = models.JSONField(
        verbose_name="To'g'ri javoblar statistikasi", default=list, blank=True,
        help_text="Har bir savolga necha marta to'g'ri javob berilganligi"
    )
    extra_ball = models.BooleanField(default=False, verbose_name="Qo'shimcha ball maydoni")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Yaratilgan sana")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="O'zgartirilgan sana")

    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, null=True, verbose_name="QR kod")

    class Meta:
        verbose_name = "Kitob Test"
        verbose_name_plural = "Kitob Testlar"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['subject', 'book_test']),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_identifier()}: {self.questions_count} savol)"

    def clean(self):
        super().clean()
        if not isinstance(self.answers, dict):
            raise ValidationError({'answers': "Javoblar dict formatida bo'lishi kerak"})
        if self.scores and not isinstance(self.scores, list):
            raise ValidationError({'scores': "Ballar list formatida bo'lishi kerak"})

    @classmethod
    def next_slug(cls):
        """Keyingi bo'sh raqamli slug ("1", "2", ...). QR kodlar shu slug bilan kitobga chop etiladi."""
        numbers = [int(s) for s in cls.objects.exclude(slug__isnull=True).values_list("slug", flat=True) if str(s).isdigit()]
        return str(max(numbers, default=0) + 1)

    def save(self, *args, **kwargs):
        if not self.answers:
            self.answers = {}
        self.questions_count = len(self.answers)

        if not self.scores:
            self.scores = [1] * self.questions_count
        elif len(self.scores) < self.questions_count:
            last_score = self.scores[-1] if self.scores else 1
            self.scores = list(self.scores) + [last_score] * (self.questions_count - len(self.scores))

        if not self.correct_answers or len(self.correct_answers) != self.questions_count:
            self.correct_answers = [0] * self.questions_count

        if not self.slug:
            self.slug = self.next_slug()

        super().save(*args, **kwargs)

        if self.slug and not self.qr_code:
            self.generate_and_save_qr_code()

    def qr_link(self):
        from django.conf import settings

        return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?startapp=test_{self.slug}"

    def generate_and_save_qr_code(self):
        """Slug asosida QR kod yaratib saqlaydi (eski faylni almashtiradi)."""
        if not self.slug:
            return
        import qrcode

        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(self.qr_link())
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')

        # Fayl nomi doim booktest_<slug>.png bo'lsin: eski fayl va shu nomdagi qoldiq faylni o'chiramiz
        filename = f'booktest_{self.slug}.png'
        storage = self.qr_code.storage
        for old in {self.qr_code.name, f"qr_codes/{filename}"} - {None, ""}:
            try:
                if storage.exists(old):
                    storage.delete(old)
            except (ValueError, NotImplementedError, OSError):
                pass
        self.qr_code.save(filename, ContentFile(buffer.getvalue()), save=False)
        super().save(update_fields=['qr_code'])

    def get_question_score(self, question_number):
        try:
            index = int(question_number) - 1
            if 0 <= index < len(self.scores):
                return self.scores[index]
        except (ValueError, TypeError):
            pass
        return 1

    def get_identifier(self):
        return self.slug if self.slug else self.id

    def get_total_score(self):
        return sum(self.scores) if self.scores else self.questions_count

    def get_grade(self, total_ball):
        return booktest_grade(total_ball)

    def check_answer(self, user_answers: dict, user=None, extra_ball=0):
        """Javoblarni tekshiradi va ballni hisoblaydi.

        Qoidalar (eski tizimdagidek): har savolning o'z bali bor; qo'shimcha ball qo'shiladi va
        test uchun extra_ball yoqilgan bo'lsa natija 2 ga bo'linadi; 65+ ball 100% hisoblanadi.
        Foydalanuvchi qayta topshirsa, avvalgi natijasi statistikadan olib tashlanadi.
        """
        try:
            correct = 0
            total_score = 0
            answers = []
            details = []

            if not self.correct_answers or len(self.correct_answers) != self.questions_count:
                self.correct_answers = [0] * self.questions_count
            if user is not None:
                old = self.results.filter(user=user).first()
                if old:
                    self._remove_old_statistics(old.user_answers)

            for q_num, right_answer in self.answers.items():
                q_index = int(q_num) - 1
                user_answer = user_answers.get(q_num)
                question_score = self.get_question_score(q_num)
                is_correct = compare_answers(user_answer, right_answer)
                details.append({
                    "question_number": int(q_num),
                    "is_correct": is_correct,
                    "user_answer": user_answer,
                    "score": question_score if is_correct else 0,
                    "max_score": question_score,
                })
                if is_correct:
                    correct += 1
                    answers.append(1)
                    if 0 <= q_index < len(self.correct_answers):
                        self.correct_answers[q_index] += 1
                    total_score += question_score
                else:
                    answers.append(0)

            try:
                extra_ball = float(extra_ball) if extra_ball else 0.0
            except (ValueError, TypeError):
                extra_ball = 0.0
            total_score += extra_ball

            max_score = self.get_total_score()
            if self.extra_ball:
                total_score = total_score / 2
                max_score = max_score / 2

            raw_percentage = (total_score / max_score * 100) if max_score > 0 else 0
            percentage = 100.0 if total_score >= 65 else round(raw_percentage, 2)
            total_score = round(total_score, 2)

            self.save(update_fields=["correct_answers", "updated_at"])

            return {
                "success": True,
                "correct": correct,
                "total": self.questions_count,
                "percentage": percentage,
                "score": total_score,
                "score_percentage": percentage,
                "passed": percentage >= 70,
                "answers": answers,
                "details": details,
                "extra_ball": extra_ball,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _compare_answers(self, user_answer, right_answer):
        return compare_answers(user_answer, right_answer)

    def _remove_old_statistics(self, old_answers):
        if not isinstance(old_answers, list):
            return
        for i, val in enumerate(old_answers):
            if i < len(self.correct_answers) and val == 1:
                self.correct_answers[i] = max(0, self.correct_answers[i] - 1)


class BookTestResult(models.Model):
    """Kitob testi natijasi (qayta topshirilsa yangilanadi)."""
    user = models.ForeignKey(
        TelegramUser, on_delete=models.CASCADE, related_name="booktest_results", verbose_name="Foydalanuvchi"
    )
    test = models.ForeignKey(BookTest, on_delete=models.CASCADE, related_name="results", verbose_name="Kitob test")
    user_answers = models.JSONField("To'g'ri/noto'g'ri (1/0)", default=list)
    submitted_answers = models.JSONField("Yuborilgan javoblar", default=dict)
    correct_answers = models.PositiveIntegerField("To'g'ri javoblar soni", default=0)
    total_questions = models.PositiveIntegerField("Umumiy savollar soni", default=0)
    extra_ball = models.FloatField("Qo'shimcha ball", default=0)
    score = models.FloatField("Ball", default=0)
    percentage = models.FloatField("Foiz", default=0)
    grade = models.CharField("Daraja", max_length=3, blank=True)
    submitted_at = models.DateTimeField("Topshirilgan sana", auto_now=True)

    class Meta:
        verbose_name = "Kitob Test Natija"
        verbose_name_plural = "Kitob Test Natijalar"
        ordering = ["-submitted_at"]
        unique_together = ["user", "test"]

    def __str__(self):
        return f"{self.user} - {self.test.title} - {self.score} ball"


# ---------------------------------------------------------------------------
# DTM (blok) testlari
#   meta = {"ona_tili": {"type": "mandatory", "questions": {"1": "A", ... "10": ...}},
#           "math_mandatory": {... 11-20}, "history": {... 21-30},
#           "<fan>": {"type": "optional", "point_per_question": 3.1, "questions": {31-60}},
#           "<fan>": {"type": "optional", "point_per_question": 2.1, "questions": {61-90}}}
#   O'quvchi javobi ham shu tuzilishda; sertifikat bo'lsa "questions" o'rniga ball (son) yuboriladi.
# ---------------------------------------------------------------------------

MANDATORY_POINT = 1.1

DTM_SUBJECT_NAMES = {
    "mother_tongue": "Ona tili",
    "mathematics": "Matematika",
    "uzbekistan_history": "O‘zbekiston tarixi",
    "physics": "Fizika",
    "english_language": "Ingliz tili",
    "arabic_language": "Arab tili",
    "biology": "Biologiya",
    "chemistry": "Kimyo",
    "law": "Huquq",
    "turkic_language": "Turk tili",
    "russian_language": "Rus tili",
    "geography": "Geografiya",
    # majburiy fanlar va eski kalitlar
    "ona_tili": "Ona tili",
    "math_mandatory": "Matematika",
    "math mandatory": "Matematika",
    "history": "O‘zbekiston tarixi",
    "math_optional": "Matematika",
}


def dtm_subject_name(key):
    return DTM_SUBJECT_NAMES.get(key) or key.replace("_", " ").capitalize()


class BlockTest(models.Model):
    creator = models.ForeignKey(
        TelegramUser, on_delete=models.CASCADE, related_name="created_block_tests",
        verbose_name="Yaratuvchi", null=True, blank=True
    )
    meta = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True, verbose_name="Faol")
    created_at = models.DateTimeField("Yaratilgan sana", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Blok Test"
        verbose_name_plural = "Blok Testlar"
        ordering = ['-id']

    def __str__(self):
        return f"BlockTest {self.id}"

    def save(self, *args, **kwargs):
        if self.pk is None and self.created_at is None:
            from django.utils import timezone

            self.created_at = timezone.now()
        super().save(*args, **kwargs)

    @staticmethod
    def points_for(conf):
        if conf.get('type') == 'mandatory':
            return MANDATORY_POINT
        if conf.get('type') == 'optional':
            try:
                return float(conf.get('point_per_question', 0))
            except (TypeError, ValueError):
                return 0
        return 0

    def blocks(self):
        """Fanlar ro'yxati (meta tartibida): kalit, nom, turi, savol raqamlari, ball."""
        result = []
        for key, conf in (self.meta or {}).items():
            if not isinstance(conf, dict):
                continue
            numbers = sorted((conf.get('questions') or {}).keys(), key=lambda k: int(k) if str(k).isdigit() else 0)
            point = self.points_for(conf)
            result.append({
                "key": key, "title": dtm_subject_name(key), "type": conf.get('type'),
                "mandatory": conf.get('type') == 'mandatory', "numbers": numbers,
                "point": point, "max_score": round(point * len(numbers), 2),
            })
        return result

    @property
    def max_score(self):
        return round(sum(b["max_score"] for b in self.blocks()), 1)

    def calculate_score(self, student_answers):
        """(umumiy ball, to'g'ri javoblar soni, fanlar bo'yicha natija) — eski tizim qoidalari bilan."""
        question_db = self.meta or {}
        total_score = 0
        total_correct = 0
        results = {}

        for subject_name, student_subject_data in (student_answers or {}).items():
            if subject_name not in question_db or not isinstance(student_subject_data, dict):
                continue

            subject_conf = question_db[subject_name]
            points_per_q = self.points_for(subject_conf)
            correct_answers_db = subject_conf.get('questions', {}) or {}
            student_qs = student_subject_data.get('questions', {})
            correct_count = 0
            subject_score = 0

            if isinstance(student_qs, (int, float)) and not isinstance(student_qs, bool):
                # Sertifikat: ball to'g'ridan-to'g'ri beriladi (fan maksimumidan oshmaydi)
                max_subject = points_per_q * len(correct_answers_db) if correct_answers_db else None
                subject_score = float(student_qs)
                if max_subject:
                    subject_score = min(subject_score, max_subject)
                correct_count = int(round(subject_score / points_per_q)) if points_per_q > 0 else 0
            elif isinstance(student_qs, dict):
                db_keys = list(correct_answers_db.keys())
                given = {str(k): v for k, v in student_qs.items()}
                # Eski frontend asosiy fan javoblarini 1..30 raqamlari bilan yuborgan, testda esa 31..60:
                # kalitlar mutlaqo mos kelmasa, tartib bo'yicha solishtiramiz
                if given and not set(given) & set(db_keys):
                    ordered = sorted(db_keys, key=lambda k: int(k) if str(k).isdigit() else 0)
                    given = {ordered[int(k) - 1]: v for k, v in given.items()
                             if str(k).isdigit() and 0 < int(k) <= len(ordered)}
                for q_num, s_ans in given.items():
                    if q_num in correct_answers_db and str(correct_answers_db[q_num]).upper() == str(s_ans).upper():
                        correct_count += 1
                        subject_score += points_per_q
                subject_score = round(subject_score, 1)

            total_score += subject_score
            total_correct += correct_count
            results[subject_name] = {
                'correct_answers': correct_count,
                'score': round(subject_score, 2),
                'points_per_question': points_per_q,
            }

        return round(total_score, 1), total_correct, results


class BlockTestResult(models.Model):
    user = models.ForeignKey(
        TelegramUser, on_delete=models.CASCADE, related_name="block_test_results", verbose_name="Foydalanuvchi"
    )
    test = models.ForeignKey(BlockTest, on_delete=models.CASCADE, related_name="results", verbose_name="Test")

    user_answers = models.JSONField(verbose_name="Foydalanuvchi javoblari", default=dict)
    total_score = models.FloatField(verbose_name="Umumiy ball", default=0.0)
    correct_answers = models.IntegerField(verbose_name="To'g'ri javoblar soni", default=0)
    detailed_results = models.JSONField(verbose_name="Batafsil natijalar", default=dict)

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Topshirilgan vaqt")

    class Meta:
        verbose_name = "Blok Test Natija"
        verbose_name_plural = "Blok Test Natijalar"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.full_name} - {self.total_score} ball"
