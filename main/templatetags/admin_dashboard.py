from django import template

from main.admin_stats import summary_stats

register = template.Library()


@register.simple_tag
def dashboard_stats():
    """Admin bosh sahifasi uchun statistika: {% dashboard_stats as stats %}"""
    return summary_stats()


@register.filter
def money(value):
    """1234567.5 -> '1 234 568'"""
    try:
        return f"{float(value):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return value
