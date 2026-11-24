import csv
from datetime import datetime
from decimal import Decimal

from django.contrib import admin, messages
from django.contrib.auth.models import Group, User
from django.db.models import Avg, Count
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from .admin_stats import full_stats, summary_stats
from .models import (
    BlockTest, BlockTestResult, BookTest, BookTestResult, Instructions, Reklama, RequiredChannel, Subject,
    TelegramUser, Test, TestResult, dtm_subject_name,
)

# Django'ning ichki User/Group modellari bu loyihada ishlatilmaydi
admin.site.unregister(User)
admin.site.unregister(Group)

admin.site.site_header = "Milliy Test — Boshqaruv paneli"
admin.site.site_title = "Milliy Test admin"
admin.site.index_title = "Bosh sahifa"
admin.site.empty_value_display = "—"


# ---------------------------------------------------------------------------
# Yordamchi funksiyalar
# ---------------------------------------------------------------------------

def badge(text, color):
    return format_html('<span class="mt-badge mt-badge-{}">{}</span>', color, text)


def admin_link(obj, text=None):
    if obj is None:
        return "—"
    url = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
    return format_html('<a href="{}">{}</a>', url, text if text is not None else obj)


def changelist_link(model, text, **filters):
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
    query = "&".join(f"{k}={v}" for k, v in filters.items())
    return format_html('<a href="{}?{}">{}</a>', url, query, text)


def export_as_csv(modeladmin, request, queryset):
    """Tanlangan yozuvlarni Excel'da ochiladigan CSV faylga yuklash."""
    fields = getattr(modeladmin, "csv_fields", None) or [f.name for f in queryset.model._meta.fields]
    labels = getattr(modeladmin, "csv_labels", {})
    name = queryset.model._meta.model_name
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="{name}_{timezone.localtime():%Y%m%d_%H%M}.csv"'
    )
    response.write("﻿")  # Excel UTF-8 ni to'g'ri o'qishi uchun BOM
    writer = csv.writer(response)
    headers = []
    for f in fields:
        if f in labels:
            headers.append(labels[f])
            continue
        try:
            headers.append(str(queryset.model._meta.get_field(f).verbose_name))
        except Exception:
            headers.append(f)
    writer.writerow(headers)
    for obj in queryset:
        row = []
        for f in fields:
            value = obj
            for part in f.split("__"):
                value = getattr(value, part, "") if value is not None else ""
            if callable(value):
                value = value()
            if isinstance(value, datetime):
                value = timezone.localtime(value).strftime("%d.%m.%Y %H:%M")
            row.append(value)
        writer.writerow(row)
    return response


export_as_csv.short_description = "📥 Tanlanganlarni CSV (Excel) ga yuklash"


# ---------------------------------------------------------------------------
# Filtrlar
# ---------------------------------------------------------------------------

class StatusFilter(admin.SimpleListFilter):
    title = "holat"
    parameter_name = "holat"

    def lookups(self, request, model_admin):
        return [("active", "✓ Faol"), ("inactive", "○ Nofaol"), ("banned", "🚫 Bloklangan")]

    def queryset(self, request, queryset):
        if self.value() == "active":
            return queryset.filter(is_active=True, is_banned=False)
        if self.value() == "inactive":
            return queryset.filter(is_active=False, is_banned=False)
        if self.value() == "banned":
            return queryset.filter(is_banned=True)
        return queryset


class HasTestsFilter(admin.SimpleListFilter):
    title = "test yaratganmi"
    parameter_name = "test_yaratgan"

    def lookups(self, request, model_admin):
        return [("yes", "Ha"), ("no", "Yo'q")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(created_tests__isnull=False).distinct()
        if self.value() == "no":
            return queryset.filter(created_tests__isnull=True)
        return queryset


class ScoreRangeFilter(admin.SimpleListFilter):
    title = "natija foizi"
    parameter_name = "foiz"

    RANGES = {
        "90": (90, 101, "90–100%"),
        "70": (70, 90, "70–89%"),
        "50": (50, 70, "50–69%"),
        "0": (0, 50, "50% dan past"),
    }

    def lookups(self, request, model_admin):
        return [(k, v[2]) for k, v in self.RANGES.items()]

    def queryset(self, request, queryset):
        if self.value() in self.RANGES:
            lo, hi, _ = self.RANGES[self.value()]
            return queryset.filter(percentage__gte=lo, percentage__lt=hi)
        return queryset


# ---------------------------------------------------------------------------
# Inline'lar
# ---------------------------------------------------------------------------

class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class UserTestResultInline(ReadOnlyInline):
    model = TestResult
    fk_name = "user"
    verbose_name_plural = "Topshirgan testlari"
    fields = ["test", "correct_answers", "total_questions", "percentage", "total_ball", "submitted_at"]
    readonly_fields = fields
    ordering = ["-submitted_at"]


class UserCreatedTestInline(ReadOnlyInline):
    model = Test
    fk_name = "creator"
    verbose_name_plural = "Yaratgan testlari"
    fields = ["title", "subject", "questions_count", "is_active", "created_at"]
    readonly_fields = fields


class TestResultInline(ReadOnlyInline):
    model = TestResult
    verbose_name_plural = "Qatnashchilar natijalari"
    fields = ["user", "correct_answers", "total_questions", "percentage", "total_ball", "submitted_at"]
    readonly_fields = fields
    ordering = ["-total_ball", "-percentage"]


# ---------------------------------------------------------------------------
# Telegram foydalanuvchilar
# ---------------------------------------------------------------------------

@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = [
        "full_name_display", "telegram_id_display", "username_display", "phone",
        "region", "district", "balance_display", "status_display", "is_admin",
        "tests_count", "results_count", "created_at",
    ]
    list_display_links = ["full_name_display"]
    list_filter = [StatusFilter, "is_admin", HasTestsFilter, "region", "created_at"]
    search_fields = ["telegram_id", "username", "name", "surname", "father_name", "phone", "district"]
    readonly_fields = ["telegram_id", "created_at", "updated_at", "summary_card"]
    date_hierarchy = "created_at"
    list_per_page = 50
    ordering = ["-created_at"]
    inlines = [UserCreatedTestInline, UserTestResultInline]
    actions = [
        "activate_users", "deactivate_users", "ban_users", "unban_users",
        "make_admin", "remove_admin", "reset_balance", export_as_csv,
    ]
    csv_fields = [
        "telegram_id", "username", "surname", "name", "father_name", "phone",
        "region", "district", "balance", "is_active", "is_banned", "is_admin", "created_at",
    ]
    fieldsets = (
        (None, {"fields": ("summary_card",)}),
        ("Telegram", {"fields": ("telegram_id", "username")}),
        ("Shaxsiy ma'lumotlar", {"fields": (("surname", "name", "father_name"), "phone")}),
        ("Manzil", {"fields": (("region", "district"),)}),
        ("Moliya", {"fields": ("balance",)}),
        ("Holat va huquqlar", {"fields": (("is_active", "is_banned", "is_admin"),)}),
        ("Sana", {"fields": (("created_at", "updated_at"),), "classes": ("collapse",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        # Yangi foydalanuvchi qo'shishda telegram_id kiritiladi
        if obj is None:
            return ["created_at", "updated_at", "summary_card"]
        return self.readonly_fields

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.fieldsets[1:]
        return self.fieldsets

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _tests_count=Count("created_tests", distinct=True),
            _results_count=Count("test_results", distinct=True),
        )

    # --- ko'rinish ustunlari ---
    @admin.display(description="F.I.Sh.", ordering="surname")
    def full_name_display(self, obj):
        return obj.full_name

    @admin.display(description="Telegram ID", ordering="telegram_id")
    def telegram_id_display(self, obj):
        return format_html('<code>{}</code>', obj.telegram_id)

    @admin.display(description="Username", ordering="username")
    def username_display(self, obj):
        if obj.username:
            return format_html('<a href="https://t.me/{0}" target="_blank" rel="noopener">@{0}</a>', obj.username)
        return "—"

    @admin.display(description="Balans", ordering="balance")
    def balance_display(self, obj):
        return f"{obj.balance:,.0f} so'm".replace(",", " ")

    @admin.display(description="Holat")
    def status_display(self, obj):
        if obj.is_banned:
            return badge("Bloklangan", "red")
        if obj.is_active:
            return badge("Faol", "green")
        return badge("Nofaol", "grey")

    @admin.display(description="Testlari", ordering="_tests_count")
    def tests_count(self, obj):
        if not obj._tests_count:
            return 0
        return changelist_link(Test, obj._tests_count, creator__id__exact=obj.pk)

    @admin.display(description="Natijalari", ordering="_results_count")
    def results_count(self, obj):
        if not obj._results_count:
            return 0
        return changelist_link(TestResult, obj._results_count, user__id__exact=obj.pk)

    @admin.display(description="Umumiy ma'lumot")
    def summary_card(self, obj):
        if not obj or not obj.pk:
            return "—"
        avg = obj.test_results.aggregate(a=Avg("percentage"))["a"]
        items = [
            ("Holat", self.status_display(obj)),
            ("Admin", badge("Ha", "gold") if obj.is_admin else badge("Yo'q", "grey")),
            ("Balans", obj.balans_formatted),
            ("Yaratgan testlari", obj.created_tests.count()),
            ("Topshirgan testlari", obj.test_results.count()),
            ("O'rtacha natija", f"{avg:.1f}%" if avg is not None else "—"),
            ("Telegram", format_html('<a href="tg://user?id={}">Profilni ochish</a>', obj.telegram_id)),
        ]
        cells = format_html_join(
            "", '<div class="mt-info"><span>{}</span><strong>{}</strong></div>', items
        )
        return format_html('<div class="mt-info-grid">{}</div>', cells)

    # --- amallar ---
    def _bulk(self, request, queryset, msg, **values):
        updated = queryset.update(**values, updated_at=timezone.now())
        self.message_user(request, f"{updated} ta foydalanuvchi {msg}.", messages.SUCCESS)

    @admin.action(description="✓ Faollashtirish")
    def activate_users(self, request, queryset):
        self._bulk(request, queryset, "faollashtirildi", is_active=True)

    @admin.action(description="○ Nofaol qilish")
    def deactivate_users(self, request, queryset):
        self._bulk(request, queryset, "nofaol qilindi", is_active=False)

    @admin.action(description="🚫 Bloklash")
    def ban_users(self, request, queryset):
        self._bulk(request, queryset, "bloklandi", is_banned=True, is_active=False)

    @admin.action(description="🔓 Blokdan chiqarish")
    def unban_users(self, request, queryset):
        self._bulk(request, queryset, "blokdan chiqarildi", is_banned=False, is_active=True)

    @admin.action(description="👑 Admin qilish")
    def make_admin(self, request, queryset):
        self._bulk(request, queryset, "admin qilindi", is_admin=True)

    @admin.action(description="Admin huquqini olish")
    def remove_admin(self, request, queryset):
        self._bulk(request, queryset, "dan admin huquqi olindi", is_admin=False)

    @admin.action(description="Balansni 0 ga tushirish")
    def reset_balance(self, request, queryset):
        self._bulk(request, queryset, "balansi 0 ga tushirildi", balance=Decimal("0.00"))

    def has_delete_permission(self, request, obj=None):
        # Foydalanuvchini o'chirish uning barcha testlari va natijalarini ham o'chiradi
        return request.user.is_superuser

    # --- statistika sahifasi ---
    def get_urls(self):
        custom = [
            path(
                "statistics/",
                self.admin_site.admin_view(self.statistics_view),
                name="main_telegramuser_statistics",
            ),
        ]
        return custom + super().get_urls()

    def statistics_view(self, request):
        context = {
            **self.admin_site.each_context(request),
            **full_stats(),
            "title": "Statistika",
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/statistics.html", context)

    def changelist_view(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), "stats": summary_stats()}
        return super().changelist_view(request, extra_context)


# ---------------------------------------------------------------------------
# Fanlar
# ---------------------------------------------------------------------------

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ["name", "tests_count", "results_count", "is_active", "created_at"]
    list_editable = ["is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["name"]
    actions = ["activate", "deactivate"]
    fieldsets = (
        (None, {"fields": ("name", "description", "is_active")}),
        ("Sana", {"fields": (("created_at", "updated_at"),), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _tests=Count("tests", distinct=True),
            _results=Count("tests__results", distinct=True),
        )

    @admin.display(description="Testlar", ordering="_tests")
    def tests_count(self, obj):
        return changelist_link(Test, obj._tests, subject__id__exact=obj.pk) if obj._tests else 0

    @admin.display(description="Natijalar", ordering="_results")
    def results_count(self, obj):
        return changelist_link(TestResult, obj._results, test__subject__id__exact=obj.pk) if obj._results else 0

    @admin.action(description="✓ Faollashtirish")
    def activate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} ta fan faollashtirildi.")

    @admin.action(description="○ Nofaol qilish")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} ta fan nofaol qilindi.")


# ---------------------------------------------------------------------------
# Testlar
# ---------------------------------------------------------------------------

@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display = [
        "id", "title", "subject", "creator_link", "questions_count",
        "participants", "avg_result", "status_display", "is_public", "start_time", "created_at",
    ]
    list_display_links = ["id", "title"]
    list_filter = ["is_active", "is_public", "subject", "created_at"]
    search_fields = ["=id", "title", "subject__name", "creator__name", "creator__surname", "creator__telegram_id"]
    autocomplete_fields = ["subject", "creator"]
    list_select_related = ["subject", "creator"]
    readonly_fields = [
        "questions_count", "answers_table", "correct_answers", "scores",
        "created_at", "updated_at",
    ]
    date_hierarchy = "created_at"
    list_per_page = 50
    inlines = [TestResultInline]
    actions = ["activate", "deactivate", "make_public", "make_private", export_as_csv]
    csv_fields = [
        "id", "title", "subject__name", "creator__full_name", "creator__telegram_id",
        "questions_count", "is_active", "is_public", "start_time", "created_at",
    ]
    csv_labels = {
        "subject__name": "Fan", "creator__full_name": "Muallif", "creator__telegram_id": "Muallif Telegram ID",
    }
    ordering = ["-created_at"]
    fieldsets = (
        (None, {"fields": ("title", ("subject", "creator"))}),
        ("Sozlamalar", {"fields": (("is_active", "is_public"), "channel_username", "start_time")}),
        ("Javoblar", {
            "fields": ("answers", "answers_table", "questions_count"),
            "description": 'Format: {"1": "A", "2": "B", ...}. Ko\'p qismli savol uchun: {"36": {"1": "JAVOB"}}',
        }),
        ("Statistika (avtomatik)", {
            "fields": ("correct_answers", "scores"),
            "classes": ("collapse",),
        }),
        ("Sana", {"fields": (("created_at", "updated_at"),), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _participants=Count("results", distinct=True),
            _avg=Avg("results__percentage"),
        )

    @admin.display(description="Muallif", ordering="creator__surname")
    def creator_link(self, obj):
        return admin_link(obj.creator, obj.creator.full_name)

    @admin.display(description="Qatnashchilar", ordering="_participants")
    def participants(self, obj):
        if not obj._participants:
            return 0
        return changelist_link(TestResult, obj._participants, test__id__exact=obj.pk)

    @admin.display(description="O'rtacha", ordering="_avg")
    def avg_result(self, obj):
        return f"{obj._avg:.1f}%" if obj._avg is not None else "—"

    @admin.display(description="Holat", ordering="is_active")
    def status_display(self, obj):
        return badge("Faol", "green") if obj.is_active else badge("Yakunlangan", "grey")

    @admin.display(description="Javoblar jadvali")
    def answers_table(self, obj):
        answers = obj.answers or {}
        if not answers:
            return "—"
        solved = obj.correct_answers or []
        participants = obj.results.count()
        scores = obj.scores or []

        def sort_key(k):
            return int(k) if str(k).isdigit() else 10**6

        rows = []
        for key in sorted(answers, key=sort_key):
            value = answers[key]
            if isinstance(value, dict):
                value = "; ".join(f"{k}) {v}" for k, v in value.items())
            elif isinstance(value, list):
                value = ", ".join(map(str, value))
            idx = sort_key(key) - 1
            correct = solved[idx] if 0 <= idx < len(solved) else None
            pct = f"{correct * 100 / participants:.0f}%" if participants and correct is not None else "—"
            score = f"{scores[idx]:.2f}" if 0 <= idx < len(scores) else "—"
            rows.append((key, value, correct if correct is not None else "—", pct, score))

        body = format_html_join(
            "", "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>", rows
        )
        return format_html(
            '<table class="mt-table"><thead><tr><th>№</th><th>To\'g\'ri javob</th>'
            "<th>Topganlar</th><th>Topganlar %</th><th>Ball (Rasch)</th></tr></thead>"
            "<tbody>{}</tbody></table>",
            body,
        )

    @admin.action(description="✓ Faollashtirish")
    def activate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} ta test faollashtirildi.")

    @admin.action(description="⏹ Yakunlangan deb belgilash")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} ta test yakunlandi.")

    @admin.action(description="🌐 Hamma uchun ochiq qilish")
    def make_public(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_public=True)} ta test ochiq qilindi.")

    @admin.action(description="🔒 Yopiq qilish")
    def make_private(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_public=False)} ta test yopiq qilindi.")


# ---------------------------------------------------------------------------
# Test natijalari
# ---------------------------------------------------------------------------

@admin.register(TestResult)
class TestResultAdmin(admin.ModelAdmin):
    list_display = [
        "user_link", "test_link", "score_display", "percentage",
        "total_ball", "grade_display", "submitted_at",
    ]
    list_filter = [ScoreRangeFilter, "test__subject", "submitted_at"]
    search_fields = ["user__name", "user__surname", "user__telegram_id", "test__title", "=test__id"]
    list_select_related = ["user", "test", "test__subject"]
    readonly_fields = [
        "user", "test", "correct_answers", "total_questions", "percentage", "total_ball",
        "grade_display", "answers_table", "submitted_at",
    ]
    date_hierarchy = "submitted_at"
    list_per_page = 50
    actions = [export_as_csv]
    csv_fields = [
        "test__id", "test__title", "user__full_name", "user__telegram_id", "user__phone",
        "user__region", "correct_answers", "total_questions", "percentage", "total_ball", "submitted_at",
    ]
    csv_labels = {
        "test__id": "Test kodi", "test__title": "Test nomi", "user__full_name": "F.I.Sh.",
        "user__telegram_id": "Telegram ID", "user__phone": "Telefon", "user__region": "Viloyat",
    }
    fieldsets = (
        (None, {"fields": (("user", "test"), "submitted_at")}),
        ("Natija", {"fields": (("correct_answers", "total_questions"), ("percentage", "total_ball"), "grade_display")}),
        ("Savollar bo'yicha", {"fields": ("answers_table",)}),
    )

    def has_add_permission(self, request):
        # Natijalar faqat foydalanuvchi test topshirganda yaratiladi
        return False

    @admin.display(description="Foydalanuvchi", ordering="user__surname")
    def user_link(self, obj):
        return admin_link(obj.user, obj.user.full_name)

    @admin.display(description="Test", ordering="test__id")
    def test_link(self, obj):
        return admin_link(obj.test, f"#{obj.test_id} {obj.test.title}")

    @admin.display(description="To'g'ri", ordering="correct_answers")
    def score_display(self, obj):
        return f"{obj.correct_answers}/{obj.total_questions}"

    @admin.display(description="Daraja")
    def grade_display(self, obj):
        if not obj.total_ball:
            return badge("Hisoblanmagan", "grey")
        grade, text = obj.get_grade()
        return badge(f"{grade} · {text}", "green" if obj.is_passed else "red")

    @admin.display(description="Javoblar")
    def answers_table(self, obj):
        marks = obj.user_answers or []
        if not marks:
            return "—"
        points = obj.earned_points or []
        cells = format_html_join(
            "",
            '<span class="mt-cell mt-cell-{}" title="{}">{}</span>',
            (
                ("ok" if m == 1 else "no", f"{points[i]:.2f} ball" if i < len(points) else "", i + 1)
                for i, m in enumerate(marks)
            ),
        )
        return format_html('<div class="mt-cells">{}</div>', cells)


# ---------------------------------------------------------------------------
# Majburiy kanallar
# ---------------------------------------------------------------------------

@admin.register(RequiredChannel)
class RequiredChannelAdmin(admin.ModelAdmin):
    list_display = ["__str__", "channel_id", "link_display", "is_active", "created_at"]
    list_display_links = ["__str__"]
    list_editable = ["is_active"]
    list_filter = ["is_active"]
    search_fields = ["channel_username", "channel_id"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        (None, {
            "fields": ("channel_id", "channel_username", "invite_link", "is_active"),
            "description": mark_safe(
                "Bot kanalda <b>administrator</b> bo'lishi shart, aks holda a'zolikni tekshira olmaydi. "
                "Kanal ID odatda <code>-100</code> bilan boshlanadi."
            ),
        }),
        ("Sana", {"fields": (("created_at", "updated_at"),), "classes": ("collapse",)}),
    )

    @admin.display(description="Havola")
    def link_display(self, obj):
        link = obj.get_link()
        return format_html('<a href="{0}" target="_blank" rel="noopener">{0}</a>', link) if link else "—"


# ---------------------------------------------------------------------------
# Yo'riqnoma
# ---------------------------------------------------------------------------

@admin.register(Instructions)
class InstructionsAdmin(admin.ModelAdmin):
    list_display = ["__str__", "preview", "updated_at"]
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        (None, {
            "fields": ("content",),
            "description": mark_safe(
                "Bot «📘 Yo'riqnoma» tugmasida <b>eng oxirgi</b> yo'riqnomani HTML formatida yuboradi. "
                "Ruxsat etilgan teglar: <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, "
                "<code>&lt;u&gt;</code>, <code>&lt;a href=\"...\"&gt;</code>, <code>&lt;code&gt;</code>."
            ),
        }),
        ("Sana", {"fields": (("created_at", "updated_at"),), "classes": ("collapse",)}),
    )

    @admin.display(description="Matn")
    def preview(self, obj):
        text = obj.content or ""
        return text[:120] + ("…" if len(text) > 120 else "")


# ---------------------------------------------------------------------------
# Kitob testlari
# ---------------------------------------------------------------------------

class BookTestResultInline(ReadOnlyInline):
    model = BookTestResult
    verbose_name_plural = "Qatnashchilar natijalari"
    fields = ["user", "correct_answers", "total_questions", "score", "percentage", "grade", "submitted_at"]
    readonly_fields = fields
    ordering = ["-score"]


@admin.register(BookTest)
class BookTestAdmin(admin.ModelAdmin):
    list_display = ["slug", "title", "subject", "creator_link", "questions_count", "max_score",
                    "participants", "book_test", "extra_ball", "qr_preview", "created_at"]
    list_display_links = ["slug", "title"]
    list_filter = ["book_test", "extra_ball", "subject", "created_at"]
    search_fields = ["=slug", "title", "subject__name", "creator__name", "creator__surname"]
    list_select_related = ["subject", "creator"]
    autocomplete_fields = ["subject", "creator"]
    readonly_fields = ["slug", "questions_count", "qr_large", "answers_table", "correct_answers", "created_at", "updated_at"]
    date_hierarchy = "created_at"
    list_per_page = 50
    inlines = [BookTestResultInline]
    actions = ["regenerate_qr", export_as_csv]
    csv_fields = ["slug", "title", "subject__name", "creator__full_name", "questions_count", "book_test", "extra_ball", "created_at"]
    csv_labels = {"subject__name": "Fan", "creator__full_name": "Muallif"}
    fieldsets = (
        (None, {"fields": (("title", "slug"), ("subject", "creator"), ("book_test", "extra_ball"))}),
        ("QR kod", {"fields": ("qr_large",)}),
        ("Javoblar va ballar", {
            "fields": ("answers", "scores", "answers_table", "questions_count"),
            "description": "scores — har bir savol bali, answers bilan bir xil tartibda: [2, 2, 1.5, ...]",
        }),
        ("Statistika", {"fields": ("correct_answers",), "classes": ("collapse",)}),
        ("Sana", {"fields": (("created_at", "updated_at"),), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_participants=Count("results", distinct=True))

    @admin.display(description="Muallif", ordering="creator__surname")
    def creator_link(self, obj):
        return admin_link(obj.creator, obj.creator.full_name)

    @admin.display(description="Maks. ball")
    def max_score(self, obj):
        total = obj.get_total_score()
        return f"{total / 2 if obj.extra_ball else total:g}"

    @admin.display(description="Qatnashchilar", ordering="_participants")
    def participants(self, obj):
        if not obj._participants:
            return 0
        return changelist_link(BookTestResult, obj._participants, test__id__exact=obj.pk)

    @admin.display(description="QR")
    def qr_preview(self, obj):
        if obj.qr_code:
            return format_html('<img src="{}" style="width:40px;height:40px">', obj.qr_code.url)
        return "—"

    @admin.display(description="QR kod")
    def qr_large(self, obj):
        if not obj or not obj.pk:
            return "Saqlangandan keyin avtomatik yaratiladi"
        img = format_html('<img src="{}" style="width:180px;height:180px"><br>', obj.qr_code.url) if obj.qr_code else ""
        return format_html('{}<a href="{}" target="_blank" rel="noopener">{}</a>', img, obj.qr_link(), obj.qr_link())

    @admin.display(description="Javoblar jadvali")
    def answers_table(self, obj):
        rows = []
        solved = obj.correct_answers or []
        for i, key in enumerate(sorted(obj.answers or {}, key=lambda k: int(k) if str(k).isdigit() else 10 ** 6)):
            value = obj.answers[key]
            if isinstance(value, dict):
                value = "; ".join(f"{k}) {v}" for k, v in value.items())
            rows.append((key, value, obj.get_question_score(key), solved[i] if i < len(solved) else "—"))
        if not rows:
            return "—"
        body = format_html_join("", "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>", rows)
        return format_html('<table class="mt-table"><thead><tr><th>№</th><th>Javob</th><th>Ball</th>'
                           '<th>Topganlar</th></tr></thead><tbody>{}</tbody></table>', body)

    @admin.action(description="🔄 QR kodni qayta yaratish")
    def regenerate_qr(self, request, queryset):
        done = 0
        for test in queryset:
            test.generate_and_save_qr_code()
            done += 1
        self.message_user(request, f"{done} ta test uchun QR kod yaratildi.")


@admin.register(BookTestResult)
class BookTestResultAdmin(admin.ModelAdmin):
    list_display = ["user_link", "test_link", "score_display", "extra_ball", "score", "percentage", "grade_display", "submitted_at"]
    list_filter = ["grade", "test__subject", "submitted_at"]
    search_fields = ["user__name", "user__surname", "user__telegram_id", "=test__slug", "test__title"]
    list_select_related = ["user", "test"]
    readonly_fields = ["user", "test", "correct_answers", "total_questions", "extra_ball", "score",
                       "percentage", "grade", "answers_cells", "submitted_at"]
    exclude = ["user_answers", "submitted_answers"]
    date_hierarchy = "submitted_at"
    actions = [export_as_csv]
    csv_fields = ["test__slug", "test__title", "user__full_name", "user__telegram_id", "user__phone",
                  "correct_answers", "total_questions", "extra_ball", "score", "percentage", "grade", "submitted_at"]
    csv_labels = {"test__slug": "Test kodi", "test__title": "Test nomi", "user__full_name": "F.I.Sh.",
                  "user__telegram_id": "Telegram ID", "user__phone": "Telefon"}

    def has_add_permission(self, request):
        return False

    @admin.display(description="Foydalanuvchi", ordering="user__surname")
    def user_link(self, obj):
        return admin_link(obj.user, obj.user.full_name)

    @admin.display(description="Kitob test", ordering="test__slug")
    def test_link(self, obj):
        return admin_link(obj.test, f"{obj.test.slug} · {obj.test.title}")

    @admin.display(description="To'g'ri", ordering="correct_answers")
    def score_display(self, obj):
        return f"{obj.correct_answers}/{obj.total_questions}"

    @admin.display(description="Daraja", ordering="grade")
    def grade_display(self, obj):
        return badge(obj.grade or "—", "red" if obj.grade in ("", "F") else "green")

    @admin.display(description="Javoblar")
    def answers_cells(self, obj):
        cells = format_html_join("", '<span class="mt-cell mt-cell-{}">{}</span>',
                                 (("ok" if m == 1 else "no", i + 1) for i, m in enumerate(obj.user_answers or [])))
        return format_html('<div class="mt-cells">{}</div>', cells) if obj.user_answers else "—"


# ---------------------------------------------------------------------------
# Reklama
# ---------------------------------------------------------------------------

REKLAMA_COLORS = {"draft": "grey", "ready": "gold", "pending": "gold", "sending": "gold",
                  "sent": "green", "completed": "green"}


@admin.register(Reklama)
class ReklamaAdmin(admin.ModelAdmin):
    list_display = ["id", "message_type", "status_display", "progress", "admin_user_id", "created_at", "completed_at"]
    list_filter = ["status", "message_type", "created_at"]
    search_fields = ["=id", "=admin_user_id", "text"]
    readonly_fields = ["admin_user_id", "message_type", "parsed_text", "buttons_json", "source_chat_id",
                       "source_message_id", "total_users", "sent_count", "failed_count", "stats_message_id",
                       "created_at", "started_at", "completed_at"]
    exclude = ["sending_users", "forward_from_chat_id", "forward_message_id", "file_id"]
    actions = ["cancel", "requeue"]

    def has_add_permission(self, request):
        # Reklama botda /reklama orqali yaratiladi (xabar Telegram'dan nusxalanadi)
        return False

    @admin.display(description="Holat", ordering="status")
    def status_display(self, obj):
        return badge(obj.get_status_display(), REKLAMA_COLORS.get(obj.status, "red"))

    @admin.display(description="Jarayon")
    def progress(self, obj):
        if not obj.total_users:
            return "—"
        done = obj.sent_count + obj.failed_count
        return format_html('{} / {} <small>(✓{} ✗{})</small>', done, obj.total_users, obj.sent_count, obj.failed_count)

    @admin.action(description="⏹ Yuborishni to'xtatish / bekor qilish")
    def cancel(self, request, queryset):
        n = queryset.exclude(status__in=["completed", "sent"]).update(status="cancelled")
        self.message_user(request, f"{n} ta reklama bekor qilindi.")

    @admin.action(description="▶️ Qolganlarga yuborishni davom ettirish")
    def requeue(self, request, queryset):
        n = queryset.filter(status__in=["cancelled", "sending", "failed", "not_sent_in_full"]).update(status="pending")
        self.message_user(request, f"{n} ta reklama navbatga qaytarildi (keyingi send_reklama ishga tushganda davom etadi).")


# ---------------------------------------------------------------------------
# Blok (DTM) testlari
# ---------------------------------------------------------------------------

class BlockTestResultInline(ReadOnlyInline):
    model = BlockTestResult
    verbose_name_plural = "Qatnashchilar natijalari"
    fields = ["user", "correct_answers", "total_score", "created_at"]
    readonly_fields = fields
    ordering = ["-total_score"]


@admin.register(BlockTest)
class BlockTestAdmin(admin.ModelAdmin):
    list_display = ["id", "subjects", "creator_link", "questions_total", "participants", "status_display", "created_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["=id", "creator__name", "creator__surname", "creator__telegram_id"]
    list_select_related = ["creator"]
    autocomplete_fields = ["creator"]
    readonly_fields = ["meta_table", "created_at"]
    inlines = [BlockTestResultInline]
    actions = ["activate", "deactivate"]
    fieldsets = (
        (None, {"fields": ("creator", "is_active", "created_at")}),
        ("Fanlar va javoblar", {"fields": ("meta_table", "meta")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_participants=Count("results", distinct=True))

    @admin.display(description="Fanlar")
    def subjects(self, obj):
        return ", ".join(b["title"] for b in obj.blocks()) or "—"

    @admin.display(description="Muallif")
    def creator_link(self, obj):
        return admin_link(obj.creator, obj.creator.full_name) if obj.creator else "—"

    @admin.display(description="Savollar")
    def questions_total(self, obj):
        return sum(len(b["numbers"]) for b in obj.blocks())

    @admin.display(description="Qatnashchilar", ordering="_participants")
    def participants(self, obj):
        if not obj._participants:
            return 0
        return changelist_link(BlockTestResult, obj._participants, test__id__exact=obj.pk)

    @admin.display(description="Holat", ordering="is_active")
    def status_display(self, obj):
        return badge("Faol", "green") if obj.is_active else badge("Yakunlangan", "grey")

    @admin.display(description="Fanlar jadvali")
    def meta_table(self, obj):
        rows = [
            (b["title"], "majburiy" if b["mandatory"] else "asosiy", b["point"],
             f"{b['numbers'][0]}–{b['numbers'][-1]}" if b["numbers"] else "—",
             " ".join(str((obj.meta[b["key"]].get("questions") or {}).get(n, "")) for n in b["numbers"]))
            for b in obj.blocks()
        ]
        if not rows:
            return "—"
        body = format_html_join("", "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td><code>{}</code></td></tr>", rows)
        return format_html('<table class="mt-table"><thead><tr><th>Fan</th><th>Turi</th><th>Ball</th>'
                           '<th>Savollar</th><th>Javoblar</th></tr></thead><tbody>{}</tbody></table>', body)

    @admin.action(description="✓ Faollashtirish")
    def activate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} ta blok test faollashtirildi.")

    @admin.action(description="⏹ Yakunlash")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} ta blok test yakunlandi.")


@admin.register(BlockTestResult)
class BlockTestResultAdmin(admin.ModelAdmin):
    list_display = ["user_link", "test_link", "correct_answers", "total_score", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["user__name", "user__surname", "user__telegram_id", "=test__id"]
    list_select_related = ["user", "test"]
    readonly_fields = ["user", "test", "correct_answers", "total_score", "details_table", "created_at"]
    exclude = ["user_answers", "detailed_results"]
    date_hierarchy = "created_at"
    actions = [export_as_csv]
    csv_fields = ["test__id", "user__full_name", "user__telegram_id", "user__phone", "correct_answers", "total_score", "created_at"]
    csv_labels = {"test__id": "Test kodi", "user__full_name": "F.I.Sh.", "user__telegram_id": "Telegram ID", "user__phone": "Telefon"}

    def has_add_permission(self, request):
        return False

    @admin.display(description="Foydalanuvchi", ordering="user__surname")
    def user_link(self, obj):
        return admin_link(obj.user, obj.user.full_name)

    @admin.display(description="Blok test", ordering="test__id")
    def test_link(self, obj):
        return admin_link(obj.test, f"#{obj.test_id}")

    @admin.display(description="Fanlar bo'yicha")
    def details_table(self, obj):
        rows = [(dtm_subject_name(k), d.get("correct_answers"), d.get("points_per_question"), d.get("score"))
                for k, d in (obj.detailed_results or {}).items()]
        if not rows:
            return "—"
        body = format_html_join("", "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>", rows)
        return format_html('<table class="mt-table"><thead><tr><th>Fan</th><th>To\'g\'ri</th><th>Savol bali</th>'
                           '<th>Ball</th></tr></thead><tbody>{}</tbody></table>', body)
