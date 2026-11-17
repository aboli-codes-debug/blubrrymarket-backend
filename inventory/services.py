"""منطق ثبت سفارش: همه‌چیز در یک تراکنش، تا یا کامل ثبت شود یا هیچ."""
from django.db import transaction

from .models import Order, OrderItem, Product, StockMovement


class OrderError(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


def create_order(user, items):
    """items: لیستی از dict با کلیدهای product_id و quantity."""
    if not isinstance(items, list) or not items:
        raise OrderError("سبد خرید خالی است.")

    wanted = {}
    for entry in items:
        try:
            product_id = int(entry["product_id"])
            quantity = int(entry["quantity"])
        except (KeyError, TypeError, ValueError):
            raise OrderError("هر آیتم باید product_id و quantity عددی داشته باشد.")
        if quantity < 1:
            raise OrderError("تعداد هر کالا باید حداقل ۱ باشد.")
        wanted[product_id] = wanted.get(product_id, 0) + quantity

    with transaction.atomic():
        # قفل ردیف‌ها تا دو خرید هم‌زمان موجودی را منفی نکنند
        products = {
            p.id: p
            for p in Product.objects.select_for_update().filter(
                id__in=wanted, is_active=True
            )
        }

        problems = []
        for product_id, quantity in wanted.items():
            product = products.get(product_id)
            if product is None:
                problems.append(
                    {"product_id": product_id, "error": "کالا پیدا نشد یا فعال نیست."}
                )
                continue
            available = product.compute_stock()
            if quantity > available:
                problems.append(
                    {
                        "product_id": product_id,
                        "name": product.name,
                        "error": "موجودی کافی نیست.",
                        "requested": quantity,
                        "available": available,
                    }
                )
        if problems:
            raise OrderError("ثبت سفارش ممکن نشد.", problems)

        order = Order.objects.create(user=user)
        for product_id, quantity in wanted.items():
            product = products[product_id]
            OrderItem.objects.create(
                order=order, product=product, quantity=quantity, unit_price=product.price
            )
            StockMovement.objects.create(
                product=product,
                kind=StockMovement.OUT,
                quantity=quantity,
                note=f"فروش - سفارش شماره {order.pk}",
                created_by=user,
                order=order,
            )
    return order
