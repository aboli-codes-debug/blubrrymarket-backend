from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from .models import Product


@staff_member_required
def stock_report(request):
    """گزارش موجودی انبار برای مدیر (فقط کاربران staff)."""
    products = Product.objects.with_stock().select_related("category").order_by("category__name", "name")

    rows = []
    total_units = 0
    total_value = 0
    for p in products:
        value = p.stock_qty * p.price
        total_units += p.stock_qty
        total_value += value
        if p.stock_qty <= 0:
            status = ("out", "تمام‌شده")
        elif p.stock_qty <= p.reorder_level:
            status = ("low", "کم‌موجود")
        else:
            status = ("ok", "موجود")
        rows.append({"product": p, "value": value, "status": status})

    return render(
        request,
        "inventory/report.html",
        {"rows": rows, "total_units": total_units, "total_value": total_value},
    )
