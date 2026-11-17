from django import forms
from django.contrib import admin
from django.db.models import F
from django.utils.html import format_html

from .models import Category, Favorite, Order, OrderItem, Product, Profile, StockMovement

admin.site.site_header = "مدیریت انبار"
admin.site.site_title = "مدیریت انبار"
admin.site.index_title = "پنل مدیریت کالاها و موجودی"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "product_count")
    search_fields = ("name",)

    @admin.display(description="تعداد کالا")
    def product_count(self, obj):
        return obj.products.count()


class StockStatusFilter(admin.SimpleListFilter):
    title = "وضعیت موجودی"
    parameter_name = "stock_status"

    def lookups(self, request, model_admin):
        return [("out", "تمام‌شده"), ("low", "کم‌موجود"), ("ok", "موجود")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "out":
            return queryset.filter(stock_qty__lte=0)
        if value == "low":
            return queryset.filter(stock_qty__gt=0, stock_qty__lte=F("reorder_level"))
        if value == "ok":
            return queryset.filter(stock_qty__gt=F("reorder_level"))
        return queryset


class StockMovementInline(admin.TabularInline):
    """افزودن ورود/خروج مستقیم از صفحه‌ی خود کالا. ردیف‌های قبلی فقط خواندنی‌اند."""

    model = StockMovement
    extra = 1
    fields = ("kind", "quantity", "note", "created_at", "created_by")
    readonly_fields = ("created_at", "created_by")
    verbose_name = "تراکنش انبار"
    verbose_name_plural = "ثبت ورود / خروج کالا"

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"
        widgets = {
            # عدد و کد چپ‌به‌راست و به‌اندازه‌ی کافی پهن، تا بریده نشوند
            "price": forms.NumberInput(attrs={"dir": "ltr", "style": "width: 14em;"}),
            "sku": forms.TextInput(attrs={"dir": "ltr", "style": "width: 14em;"}),
            "reorder_level": forms.NumberInput(attrs={"dir": "ltr", "style": "width: 8em;"}),
        }


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = (
        "name", "sku", "category", "price_display",
        "stock_display", "status_display", "is_active",
    )
    list_filter = (StockStatusFilter, "category", "is_active")
    list_editable = ("is_active",)
    search_fields = ("name", "sku")
    list_select_related = ("category",)
    inlines = [StockMovementInline]
    fieldsets = (
        (None, {"fields": ("name", "sku", "category", "price", "image", "description")}),
        ("انبار و نمایش", {"fields": ("reorder_level", "is_active")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).with_stock()

    @admin.display(description="قیمت (تومان)", ordering="price")
    def price_display(self, obj):
        return f"{obj.price:,}"

    @admin.display(description="موجودی", ordering="stock_qty")
    def stock_display(self, obj):
        return obj.stock_qty

    @admin.display(description="وضعیت")
    def status_display(self, obj):
        if obj.stock_qty <= 0:
            return format_html('<b style="color:#c0392b">● تمام‌شده</b>')
        if obj.stock_qty <= obj.reorder_level:
            return format_html('<b style="color:#d68910">● کم‌موجود</b>')
        return format_html('<b style="color:#1e8449">● موجود</b>')

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, StockMovement) and instance.pk is None:
                instance.created_by = request.user
            instance.save()
        formset.save_m2m()


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """دفتر کل انبار: ثبت ورود/خروج جدید ممکن است، ولی سابقه قابل ویرایش و حذف نیست."""

    list_display = ("created_at", "product", "kind", "quantity", "note", "created_by", "order")
    list_filter = ("kind", "product__category")
    search_fields = ("product__name", "product__sku", "note")
    autocomplete_fields = ("product",)
    fields = ("product", "kind", "quantity", "note")
    date_hierarchy = "created_at"

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.created_by = request.user
        super().save_model(request, obj, form, change)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "quantity", "unit_price")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "created_at", "total_display")
    list_filter = ("created_at",)
    search_fields = ("user__username",)
    inlines = [OrderItemInline]

    @admin.display(description="جمع کل (تومان)")
    def total_display(self, obj):
        return f"{obj.total_price:,}"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "short_bio", "has_photo")
    search_fields = ("user__username", "user__email")

    @admin.display(description="درباره‌ی من")
    def short_bio(self, obj):
        return (obj.bio[:40] + "…") if len(obj.bio) > 40 else obj.bio

    @admin.display(description="عکس", boolean=True)
    def has_photo(self, obj):
        return bool(obj.photo)


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "created_at")
    list_filter = ("product",)
    search_fields = ("user__username", "product__name")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
