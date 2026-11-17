from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Case, F, IntegerField, Sum, When
from django.db.models.functions import Coalesce


class Category(models.Model):
    name = models.CharField("نام دسته‌بندی", max_length=100, unique=True)

    class Meta:
        verbose_name = "دسته‌بندی"
        verbose_name_plural = "دسته‌بندی‌ها"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def with_stock(self):
        """به هر محصول فیلد stock_qty (ورودی‌ها منهای خروجی‌ها) اضافه می‌کند."""
        return self.annotate(
            stock_qty=Coalesce(
                Sum(
                    Case(
                        When(movements__kind="in", then=F("movements__quantity")),
                        When(movements__kind="out", then=F("movements__quantity") * -1),
                        output_field=IntegerField(),
                    )
                ),
                0,
            )
        )


class Product(models.Model):
    name = models.CharField("نام کالا", max_length=200)
    sku = models.CharField("کد کالا", max_length=50, unique=True)
    category = models.ForeignKey(
        Category,
        verbose_name="دسته‌بندی",
        on_delete=models.PROTECT,
        related_name="products",
    )
    price = models.PositiveIntegerField("قیمت (تومان)")
    description = models.TextField("توضیحات", blank=True)
    image = models.ImageField("عکس", upload_to="products/", blank=True)
    reorder_level = models.PositiveIntegerField(
        "حد سفارش مجدد",
        default=5,
        help_text="وقتی موجودی به این عدد یا کمتر برسد، «کم‌موجود» نشان داده می‌شود.",
    )
    is_active = models.BooleanField(
        "نمایش در فروشگاه", default=True,
        help_text="با برداشتن تیک، کالا از اپ فروشگاه مخفی می‌شود (بدون پاک شدن).",
    )
    created_at = models.DateTimeField("تاریخ ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        verbose_name = "کالا"
        verbose_name_plural = "کالاها"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def compute_stock(self):
        """موجودی فعلی را مستقیم از تاریخچه‌ی انبار حساب می‌کند."""
        return (
            Product.objects.with_stock()
            .filter(pk=self.pk)
            .values_list("stock_qty", flat=True)
            .first()
            or 0
        )

    @property
    def current_stock(self):
        if hasattr(self, "stock_qty"):  # وقتی از with_stock() آمده باشد
            return self.stock_qty
        return self.compute_stock()


class Order(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="مشتری",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "سفارش"
        verbose_name_plural = "سفارش‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"سفارش #{self.pk}"

    @property
    def total_price(self):
        return sum(item.line_total for item in self.items.all())


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, verbose_name="کالا", on_delete=models.PROTECT, related_name="order_items"
    )
    quantity = models.PositiveIntegerField("تعداد", validators=[MinValueValidator(1)])
    unit_price = models.PositiveIntegerField("قیمت واحد (تومان)")

    class Meta:
        verbose_name = "آیتم سفارش"
        verbose_name_plural = "آیتم‌های سفارش"

    @property
    def line_total(self):
        return self.quantity * self.unit_price


class StockMovement(models.Model):
    """هر ورود یا خروج کالا. موجودی = جمع ورودی‌ها − جمع خروجی‌ها."""

    IN = "in"
    OUT = "out"
    KIND_CHOICES = [(IN, "ورود به انبار"), (OUT, "خروج از انبار")]

    product = models.ForeignKey(
        Product, verbose_name="کالا", on_delete=models.CASCADE, related_name="movements"
    )
    kind = models.CharField("نوع", max_length=3, choices=KIND_CHOICES, default=IN)
    quantity = models.PositiveIntegerField("تعداد", validators=[MinValueValidator(1)])
    note = models.CharField("توضیح", max_length=255, blank=True)
    created_at = models.DateTimeField("تاریخ", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ثبت‌کننده",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    order = models.ForeignKey(
        Order,
        verbose_name="سفارش",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="movements",
    )

    class Meta:
        verbose_name = "تراکنش انبار"
        verbose_name_plural = "تاریخچه‌ی انبار"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.product.name} × {self.quantity}"

    def clean(self):
        # جلوی خروج بیشتر از موجودی را در فرم‌های ادمین می‌گیرد
        if self.pk is None and self.kind == self.OUT and self.product_id and self.quantity:
            available = self.product.compute_stock()
            if self.quantity > available:
                raise ValidationError(
                    f"موجودی کافی نیست: موجودی فعلی «{self.product.name}» "
                    f"{available} عدد است."
                )


class Profile(models.Model):
    """اطلاعات پروفایل مشتری (بیو و عکس) که اپ دسکتاپ از طریق API می‌خواند و می‌نویسد."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        on_delete=models.CASCADE,
        related_name="profile",
    )
    bio = models.TextField("درباره‌ی من", blank=True)
    photo = models.ImageField("عکس پروفایل", upload_to="profiles/", blank=True)

    class Meta:
        verbose_name = "پروفایل مشتری"
        verbose_name_plural = "پروفایل مشتری‌ها"

    def __str__(self):
        return f"پروفایل {self.user}"


class Favorite(models.Model):
    """کالاهای مورد علاقه‌ی هر مشتری (♥ در اپ)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )
    product = models.ForeignKey(
        Product, verbose_name="کالا", on_delete=models.CASCADE, related_name="favorited_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "علاقه‌مندی"
        verbose_name_plural = "علاقه‌مندی‌ها"
        unique_together = [("user", "product")]

    def __str__(self):
        return f"{self.user} ♥ {self.product}"
