"""Admin panel uchun statistikani hisoblash (bosh sahifa va statistika sahifasi)."""
from datetime import timedelta

from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import (
    BlockTest, BlockTestResult, BookTest, BookTestResult, RequiredChannel, Subject, TelegramUser, Test, TestResult,
)


def _percent(part, total):
    return round(part * 100 / total, 1) if total else 0


def summary_stats():
    """Bosh sahifadagi kartochkalar uchun qisqa statistika."""
    now = timezone.localtime()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    users = TelegramUser.objects.all()
    results = TestResult.objects.all()

    return {
        "users_total": users.count(),
        "users_active": users.filter(is_active=True, is_banned=False).count(),
        "users_banned": users.filter(is_banned=True).count(),
        "users_admin": users.filter(is_admin=True).count(),
        "users_today": users.filter(created_at__gte=today).count(),
        "users_week": users.filter(created_at__gte=week_ago).count(),
        "balance_total": users.aggregate(s=Sum("balance"))["s"] or 0,
        "subjects_total": Subject.objects.count(),
        "tests_total": Test.objects.count(),
        "tests_active": Test.objects.filter(is_active=True).count(),
        "tests_week": Test.objects.filter(created_at__gte=week_ago).count(),
        "results_total": results.count(),
        "results_week": results.filter(submitted_at__gte=week_ago).count(),
        "avg_percentage": round(float(results.aggregate(a=Avg("percentage"))["a"] or 0), 1),
        "channels_active": RequiredChannel.objects.filter(is_active=True).count(),
        "booktests_total": BookTest.objects.count(),
        "booktest_results": BookTestResult.objects.count(),
        "blocktests_total": BlockTest.objects.count(),
        "blocktests_active": BlockTest.objects.filter(is_active=True).count(),
        "blocktest_results": BlockTestResult.objects.count(),
    }


def _daily_series(queryset, field, days):
    """Oxirgi `days` kun uchun har kunlik sonlar ro'yxati (bo'sh kunlar 0 bilan)."""
    start = (timezone.localtime() - timedelta(days=days - 1)).date()
    counts = {
        row["day"]: row["n"]
        for row in queryset.filter(**{f"{field}__date__gte": start})
        .annotate(day=TruncDate(field))
        .values("day")
        .annotate(n=Count("id"))
    }
    series = [
        {"day": start + timedelta(days=i), "count": counts.get(start + timedelta(days=i), 0)}
        for i in range(days)
    ]
    peak = max((d["count"] for d in series), default=0)
    for d in series:
        d["height"] = _percent(d["count"], peak)
    return series


def full_stats(days=14):
    """Statistika sahifasi uchun batafsil ma'lumotlar."""
    stats = summary_stats()
    users_total = stats["users_total"]

    regions = list(
        TelegramUser.objects.values("region").annotate(count=Count("id")).order_by("-count")
    )
    for r in regions:
        r["percent"] = _percent(r["count"], users_total)

    top_tests = (
        Test.objects.select_related("subject", "creator")
        .annotate(participants=Count("results"), avg_pct=Avg("results__percentage"))
        .filter(participants__gt=0)
        .order_by("-participants")[:10]
    )

    top_creators = (
        TelegramUser.objects.annotate(
            tests_count=Count("created_tests", distinct=True),
            participants=Count("created_tests__results", distinct=True),
        )
        .filter(tests_count__gt=0)
        .order_by("-tests_count", "-participants")[:10]
    )

    subjects = Subject.objects.annotate(
        tests_count=Count("tests", distinct=True),
        results_count=Count("tests__results", distinct=True),
    ).order_by("-tests_count")

    stats.update(
        {
            "days": days,
            "registrations": _daily_series(TelegramUser.objects.all(), "created_at", days),
            "submissions": _daily_series(TestResult.objects.all(), "submitted_at", days),
            "regions": regions,
            "top_tests": top_tests,
            "top_creators": top_creators,
            "subjects": subjects,
            "recent_users": TelegramUser.objects.order_by("-created_at")[:10],
        }
    )
    return stats
