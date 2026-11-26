from django.conf import settings
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from main.bot import get_main_menu, user_send_message
from main.models import BlockTest, BlockTestResult, BookTest, BookTestResult, Subject, TelegramUser, Test, TestResult
from main.regions import REGIONS
from main.services import (
    DTM_MANDATORY_BLOCKS, DTM_OPTIONAL_SUBJECTS, GRADE_MESSAGES, MANDATORY_CERTIFICATE_SCORE, SubmissionError,
    build_block_meta, certificate_value, notify_block_test_created, notify_booktest_created, notify_test_created,
    submit_block_test, submit_booktest, submit_test_answers, test_open_error,
)
from main.telegram_auth import validate_init_data

from .auth import allow_telegram_frame, login_telegram, telegram_page
from .forms import (
    CHOICES_4, SINGLE_4, SINGLE_6, WRITTEN_BLOCKS, WRITTEN_MAX_PARTS, WRITTEN_START,
    BookTestForm, DtmTestForm, NationalTestForm, RegisterForm, options_for,
)


def posted_values(request):
    """Xato bo'lsa formani qayta to'ldirish uchun yuborilgan qiymatlar."""
    if request.method != "POST":
        return None
    return {k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"}


def safe_next(request, url, default):
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}):
        return url
    return default


# ---------------------------------------------------------------------------
# Autentifikatsiya
# ---------------------------------------------------------------------------

@csrf_exempt  # initData bot tokeni bilan imzolangan — CSRF cookie bo'lmasa ham (iframe, yangi sessiya) kira olsin
@require_POST
def auth(request):
    """Telegram initData'ni tekshiradi va sessiya ochadi."""
    data = validate_init_data(request.POST.get("init_data", ""))
    if data is None:
        return allow_telegram_frame(JsonResponse({"ok": False, "error": "Telegram ma'lumotlari tasdiqlanmadi"}, status=403))
    login_telegram(request, data["user"])

    next_url = safe_next(request, request.POST.get("next"), reverse("webapp:home"))
    start_param = data.get("start_param", "")
    if start_param.startswith("test_") and start_param[5:].isdigit():
        # Kitobdagi QR kodlar: ?startapp=test_<slug>. Bunday kitob testi bo'lmasa — Milliy test kodi
        code = start_param[5:]
        if BookTest.objects.filter(slug=code).exists():
            next_url = reverse("webapp:booktest_sheet", args=[code])
        else:
            next_url = reverse("webapp:send_sheet", args=[int(code)])
    elif start_param.startswith("dtm_") and start_param[4:].isdigit():
        next_url = reverse("webapp:dtm_sheet", args=[int(start_param[4:])])
    return allow_telegram_frame(JsonResponse({"ok": True, "next": next_url}))


# ---------------------------------------------------------------------------
# Fanlar va ochiq testlar
# ---------------------------------------------------------------------------

@telegram_page()
def home(request):
    subjects = Subject.objects.filter(is_active=True).annotate(
        public_count=Count("tests", filter=Q(tests__is_public=True))
    ).order_by("name")
    return render(request, "webapp/home.html", {"subjects": subjects, "nav": "home"})


@telegram_page()
def subject_tests(request, pk):
    subject = get_object_or_404(Subject, pk=pk)
    tests = subject.tests.filter(is_public=True).order_by("-is_active", "-start_time", "-created_at")
    return render(request, "webapp/subject.html", {"subject": subject, "tests": tests, "nav": "home"})


# ---------------------------------------------------------------------------
# Ro'yxatdan o'tish va profil
# ---------------------------------------------------------------------------

@telegram_page()
def register(request):
    user = request.tg_user
    next_url = request.GET.get("next") or request.POST.get("next")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            fields = {k: data[k] for k in ("name", "surname", "father_name", "phone", "region", "district")}
            if request.tg.get("username"):
                fields["username"] = request.tg["username"][:50]
            created = user is None
            try:
                user, created = TelegramUser.objects.update_or_create(telegram_id=request.tg["id"], defaults=fields)
            except IntegrityError:
                user = TelegramUser.objects.get(telegram_id=request.tg["id"])
                created = False
            if created:
                user_send_message(
                    user.telegram_id,
                    "✅ Ro‘yxatdan muvaffaqiyatli o‘tdingiz!\n\n👇 Quyidagilardan birini tanlang:",
                    markup=get_main_menu(user),
                )
            default = reverse("webapp:home") if created else reverse("webapp:profile")
            return redirect(safe_next(request, next_url, default))
    elif user:
        form = RegisterForm(initial={
            "name": user.name, "surname": user.surname, "father_name": user.father_name or "",
            "phone": user.phone, "region": user.region, "district": user.district,
        })
    else:
        form = RegisterForm(initial={
            "name": request.tg.get("first_name", ""), "surname": request.tg.get("last_name", ""), "phone": "+998",
        })

    return render(request, "webapp/register.html", {
        "form": form, "editing": user is not None, "next": next_url or "",
        "regions": REGIONS, "hide_nav": user is None,
    })


@telegram_page(require_registration=True)
def profile(request):
    user = request.tg_user
    stats = {
        "tests_created": (user.created_tests.count() + user.created_block_tests.count()
                          + user.created_booktests.count()),
        "tests_taken": (user.test_results.count() + user.block_test_results.count()
                        + user.booktest_results.count()),
    }
    recent = user.test_results.select_related("test", "test__subject").order_by("-submitted_at")[:5]
    return render(request, "webapp/profile.html", {"user": user, "stats": stats, "recent": recent, "nav": "profile"})


# ---------------------------------------------------------------------------
# Test yaratish
# ---------------------------------------------------------------------------

@telegram_page(require_registration=True)
def create_option(request):
    return render(request, "webapp/create_option.html", {"nav": "create"})


@telegram_page(require_registration=True)
def create_national(request):
    form = NationalTestForm(request.POST) if request.method == "POST" else None
    if form and form.is_valid():
        c = form.cleaned
        test = Test.objects.create(
            subject=c["subject"], creator=request.tg_user, title=c["subject"].name,
            is_public=c["is_public"], channel_username=c["channel_username"],
            start_time=c["start_time"], answers=c["answers"],
        )
        notify_test_created(test)
        return redirect("webapp:test_created", pk=test.pk)

    return render(request, "webapp/create_national.html", {
        "subjects": Subject.objects.filter(is_active=True).order_by("name"),
        "errors": form.errors if form else [],
        "posted": posted_values(request),
        "single_4": SINGLE_4, "single_6": SINGLE_6, "choices_4": CHOICES_4, "choices_6": options_for(33),
        "written_blocks": range(WRITTEN_START, WRITTEN_START + WRITTEN_BLOCKS),
        "written_max": WRITTEN_MAX_PARTS, "nav": "create",
    })


def dtm_create_blocks():
    """Yaratish sahifasi uchun bloklar: (form prefiksi, sarlavha, savollar soni, ball)."""
    from main.models import dtm_subject_name

    blocks = [{"key": "main_1", "title": "Birinchi asosiy fan", "numbers": range(1, 31), "point": 3.1, "main": True},
              {"key": "main_2", "title": "Ikkinchi asosiy fan", "numbers": range(1, 31), "point": 2.1, "main": True}]
    for key, numbers in DTM_MANDATORY_BLOCKS:
        blocks.append({"key": key, "title": dtm_subject_name(key), "numbers": range(1, len(numbers) + 1),
                       "point": 1.1, "main": False})
    return blocks


@telegram_page(require_registration=True)
def create_dtm(request):
    form = DtmTestForm(request.POST) if request.method == "POST" else None
    if form and form.is_valid():
        c = form.cleaned
        test = BlockTest.objects.create(
            creator=request.tg_user,
            meta=build_block_meta(c["main_subject_1"], c["main_subject_2"], c["answers"]),
        )
        notify_block_test_created(test)
        return redirect("webapp:dtm_created", pk=test.pk)

    return render(request, "webapp/create_dtm.html", {
        "subjects": DTM_OPTIONAL_SUBJECTS, "blocks": dtm_create_blocks(), "choices": CHOICES_4,
        "errors": form.errors if form else [], "posted": posted_values(request), "nav": "create",
    })


@telegram_page(require_registration=True)
def test_created(request, pk):
    test = get_object_or_404(Test, pk=pk, creator=request.tg_user)
    return render(request, "webapp/created.html", {
        "code": test.pk, "title": f"{test.subject.name} — Milliy sertifikat testi",
        "commands": [f"/natija_{test.pk}", f"/yakunlash_{test.pk}"], "nav": "create",
    })


@telegram_page(require_registration=True)
def dtm_created(request, pk):
    test = get_object_or_404(BlockTest, pk=pk, creator=request.tg_user)
    return render(request, "webapp/created.html", {
        "code": test.pk, "title": "Blok test: " + ", ".join(b["title"] for b in test.blocks()),
        "commands": [f"/natijablock_{test.pk}", f"/stop_block_{test.pk}"], "nav": "create",
    })


# ---------------------------------------------------------------------------
# Milliy sertifikat testiga javob yuborish
# ---------------------------------------------------------------------------

def national_sheet(test):
    """Javob varag'i tuzilishi — to'g'ri javoblarning o'zi brauzerga yuborilmaydi."""
    def num(k):
        return int(k) if str(k).isdigit() else 10 ** 6

    choice_4, choice_6, written = [], [], []
    for key in sorted(test.answers or {}, key=num):
        n, right = num(key), test.answers[key]
        if isinstance(right, dict):
            written.append({"n": n, "parts": list(right.keys())})
        elif n <= 32:
            choice_4.append(n)
        else:
            choice_6.append(n)
    return choice_4, choice_6, written


def collect_sheet_answers(post, choice_4, choice_6, written):
    """Javob varag'idan (q_N radio, w_N_qism yozma) javoblar lug'atini yig'adi; bo'sh javoblar tashlanadi."""
    answers = {}
    for n in choice_4 + choice_6:
        v = (post.get(f"q_{n}") or "").strip().upper()
        if v in options_for(n):
            answers[str(n)] = v
    for w in written:
        parts = {p: (post.get(f"w_{w['n']}_{p}") or "").strip().upper() for p in w["parts"]}
        parts = {p: v for p, v in parts.items() if v}
        if parts:
            answers[str(w["n"])] = parts
    return answers


@telegram_page(require_registration=True)
def send_test(request):
    code = (request.GET.get("code") or "").strip()
    error = None
    if code:
        if not code.isdigit():
            error = "Faqat raqam kiritilishi kerak!"
        elif not Test.objects.filter(pk=int(code)).exists():
            error = "Test topilmadi"
        else:
            return redirect("webapp:send_sheet", pk=int(code))
    return render(request, "webapp/code_entry.html", {
        "title": "Testni yuborish", "code": code, "error": error,
        "action": reverse("webapp:send_test"), "nav": "send",
    })


@telegram_page(require_registration=True)
def send_sheet(request, pk):
    test = Test.objects.select_related("subject").filter(pk=pk).first()
    if test is None:
        return render(request, "webapp/code_entry.html", {
            "title": "Testni yuborish", "code": pk, "error": "Test topilmadi",
            "action": reverse("webapp:send_test"), "nav": "send",
        })
    reason = test_open_error(test)
    if reason:
        return render(request, "webapp/code_entry.html", {
            "title": "Testni yuborish", "code": pk, "error": reason,
            "action": reverse("webapp:send_test"), "nav": "send",
        })

    choice_4, choice_6, written = national_sheet(test)
    error = None
    if request.method == "POST":
        answers = collect_sheet_answers(request.POST, choice_4, choice_6, written)
        try:
            submit_test_answers(test, request.tg_user, answers, request=request)
        except SubmissionError as e:
            error = str(e)
        else:
            return render(request, "webapp/submitted.html", {"test": test, "nav": "send"})

    previous = TestResult.objects.filter(test=test, user=request.tg_user).first()
    return render(request, "webapp/send_sheet.html", {
        "test": test, "choice_4": choice_4, "choice_6": choice_6, "written": written,
        "choices_4": CHOICES_4, "choices_6": options_for(33),
        "previous": previous, "error": error, "posted": posted_values(request), "nav": "send",
        "title": f"{test.subject.name} testni yuborish", "code": test.pk, "back_url": reverse("webapp:send_test"),
    })


@telegram_page()
def start(request, pk):
    return redirect("webapp:send_sheet", pk=pk)


# ---------------------------------------------------------------------------
# DTM testiga javob yuborish
# ---------------------------------------------------------------------------

@telegram_page(require_registration=True)
def dtm(request):
    code = (request.GET.get("code") or "").strip()
    error = None
    if code:
        if not code.isdigit():
            error = "Faqat raqam kiritilishi kerak!"
        elif not BlockTest.objects.filter(pk=int(code)).exists():
            error = "Test topilmadi"
        else:
            return redirect("webapp:dtm_sheet", pk=int(code))
    return render(request, "webapp/code_entry.html", {
        "title": "DTM testni yuborish", "code": code, "error": error,
        "action": reverse("webapp:dtm"), "nav": "dtm",
    })


@telegram_page(require_registration=True)
def dtm_sheet(request, pk):
    test = BlockTest.objects.filter(pk=pk).first()
    if test is None or not test.is_active:
        return render(request, "webapp/code_entry.html", {
            "title": "DTM testni yuborish", "code": pk,
            "error": "Test topilmadi" if test is None else "Ushbu test yakunlangan yoki faol emas",
            "action": reverse("webapp:dtm"), "nav": "dtm",
        })

    blocks = test.blocks()
    for i, b in enumerate(blocks):
        b["idx"] = i
        b["rows"] = list(enumerate(b["numbers"], start=1))  # (ko'rsatiladigan raqam, asl savol raqami)

    error = None
    if request.method == "POST":
        try:
            user_answers = {}
            for b in blocks:
                cert = request.POST.get(f"cert_{b['idx']}")
                if b["mandatory"]:
                    # Majburiy fan sertifikati — to'liq ball (10 × 1.1 = 11)
                    questions = b["max_score"] if cert == "on" else None
                else:
                    questions = certificate_value(cert, b["max_score"])
                if questions is None:
                    questions = {}
                    for shown, number in b["rows"]:
                        v = (request.POST.get(f"b{b['idx']}_{shown}") or "").strip().upper()
                        if v in CHOICES_4:
                            questions[number] = v
                entry = {"type": b["type"], "questions": questions}
                if not b["mandatory"]:
                    entry["point_per_question"] = b["point"]
                user_answers[b["key"]] = entry
            total, correct, detailed, _ = submit_block_test(test, request.tg_user, user_answers, request=request)
        except SubmissionError as e:
            error = str(e)
        else:
            rows = [{"title": b["title"], "correct": detailed.get(b["key"], {}).get("correct_answers", 0),
                     "questions": len(b["numbers"]), "score": detailed.get(b["key"], {}).get("score", 0),
                     "certificate": not isinstance(user_answers[b["key"]]["questions"], dict)} for b in blocks]
            return render(request, "webapp/dtm_result.html", {
                "test": test, "total": total, "correct": correct, "rows": rows, "nav": "dtm",
            })

    previous = BlockTestResult.objects.filter(test=test, user=request.tg_user).first()
    return render(request, "webapp/dtm_sheet.html", {
        "test": test, "blocks": blocks, "choices": CHOICES_4, "previous": previous,
        "mandatory_certificate": MANDATORY_CERTIFICATE_SCORE,
        "error": error, "posted": posted_values(request), "nav": "dtm",
    })


# ---------------------------------------------------------------------------
# Kitob testlari (QR: ?startapp=test_<slug>)
# ---------------------------------------------------------------------------

def booktest_entry(request, code="", error=None):
    return render(request, "webapp/code_entry.html", {
        "title": "Kitob testi", "code": code, "error": error,
        "action": reverse("webapp:booktest"), "nav": "send",
    })


@telegram_page(require_registration=True)
def booktest(request):
    code = (request.GET.get("code") or "").strip()
    if not code:
        return booktest_entry(request)
    if not BookTest.objects.filter(slug=code).exists():
        return booktest_entry(request, code, "Test topilmadi")
    return redirect("webapp:booktest_sheet", slug=code)


@telegram_page(require_registration=True)
def booktest_sheet(request, slug):
    test = BookTest.objects.select_related("subject").filter(slug=slug).first()
    if test is None:
        return booktest_entry(request, slug, "Test topilmadi")

    choice_4, choice_6, written = national_sheet(test)
    error = None
    if request.method == "POST":
        answers = collect_sheet_answers(request.POST, choice_4, choice_6, written)
        try:
            result, grade, _ = submit_booktest(test, request.tg_user, answers,
                                               request.POST.get("extra_ball") if test.extra_ball else 0,
                                               request=request)
        except SubmissionError as e:
            error = str(e)
        else:
            return render(request, "webapp/booktest_result.html", {
                "test": test, "result": result, "grade": grade,
                "message": GRADE_MESSAGES.get(grade, ""), "nav": "send",
            })

    previous = BookTestResult.objects.filter(test=test, user=request.tg_user).first()
    return render(request, "webapp/send_sheet.html", {
        "test": test, "title": test.title, "code": test.slug, "back_url": reverse("webapp:booktest"),
        "choice_4": choice_4, "choice_6": choice_6, "written": written,
        "choices_4": CHOICES_4, "choices_6": options_for(33), "extra_ball": test.extra_ball,
        "previous": previous, "error": error, "posted": posted_values(request), "nav": "send",
    })


@telegram_page(require_registration=True)
def booktest_create(request):
    if not request.tg_user.is_admin:
        return render(request, "webapp/forbidden.html",
                      {"nav": "create", "message": "Kitob testlarini faqat adminlar yarata oladi."}, status=403)
    form = BookTestForm(request.POST) if request.method == "POST" else None
    if form and form.is_valid():
        test = BookTest.objects.create(creator=request.tg_user, **form.cleaned)
        notify_booktest_created(test)
        return redirect("webapp:booktest_created", slug=test.slug)

    return render(request, "webapp/create_national.html", {
        "booktest": True,
        "subjects": Subject.objects.order_by("name"),
        "errors": form.errors if form else [], "posted": posted_values(request),
        "single_4": SINGLE_4, "single_6": SINGLE_6, "choices_4": CHOICES_4, "choices_6": options_for(33),
        "written_blocks": range(WRITTEN_START, WRITTEN_START + WRITTEN_BLOCKS),
        "written_max": WRITTEN_MAX_PARTS, "nav": "create",
    })


@telegram_page(require_registration=True)
def booktest_created(request, slug):
    test = get_object_or_404(BookTest, slug=slug, creator=request.tg_user)
    return render(request, "webapp/created.html", {
        "code": test.slug, "title": f"Kitob testi: {test.title}", "qr": test.qr_code.url if test.qr_code else None,
        "link": test.qr_link(), "commands": [f"/kitobnatija_{test.slug}"], "nav": "create",
    })


def csrf_failure(request, reason=""):
    """CSRF xatosi (sahifa uzoq ochiq turgan, cookie o'chgan...) — tushunarli sahifa va qayta urinish."""
    if request.path.startswith(("/admin", "/api")):
        from django.views.csrf import csrf_failure as default_failure

        return default_failure(request, reason)
    response = render(request, "webapp/forbidden.html", {
        "heading": "Sahifa eskirgan", "back_url": request.get_full_path(), "hide_nav": True,
        "message": "Xavfsizlik tekshiruvidan o'tmadi. Sahifani qayta ochib, ma'lumotlarni yana yuboring.",
    }, status=403)
    return allow_telegram_frame(response)


def bot_redirect(request):
    """Telegram'dan tashqarida ochilganda botga yo'naltirish uchun."""
    return redirect(f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}")
