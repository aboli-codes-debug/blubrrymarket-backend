from django.core.management.base import BaseCommand

from inventory.models import Category, Product, StockMovement


class Command(BaseCommand):
    help = "چند کالای نمونه (همان کالاهای فروشگاه PyQt) و موجودی اولیه می‌سازد."

    def handle(self, *args, **options):
        if Product.objects.exists():
            self.stdout.write("کالا از قبل وجود دارد؛ چیزی اضافه نشد.")
            return

        mobile, _ = Category.objects.get_or_create(name="Mobile & Tablet")
        demo = [
            ("iPhone 17", "IPH-17", 25_000_000, 12),
            ("poco", "POCO-1", 25_000_000, 8),
            ("f70", "F70-1", 25_000_000, 3),
        ]
        for name, sku, price, qty in demo:
            product = Product.objects.create(
                name=name, sku=sku, category=mobile, price=price
            )
            StockMovement.objects.create(
                product=product, kind=StockMovement.IN, quantity=qty,
                note="موجودی اولیه",
            )
        self.stdout.write(self.style.SUCCESS("۳ کالای نمونه ساخته شد."))
