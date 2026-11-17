from django import template

register = template.Library()


@register.filter
def money(value):
    """۲۵۰۰۰۰۰۰ ← 25,000,000 (قالب فارسی Django جداکننده‌ی هزارگان ندارد)."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value
