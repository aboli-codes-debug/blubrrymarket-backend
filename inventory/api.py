"""API ساده‌ی JSON برای اپ دسکتاپ فروشگاه.

فهرست کالاها عمومی است (فقط خواندنی). ثبت سفارش نیاز به توکن ورود دارد.
اپ هرگز مستقیم به دیتابیس وصل نمی‌شود.
"""
import json
from functools import wraps
from io import BytesIO

from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import validate_email
from django.db import IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from PIL import Image

from .models import Category, Favorite, Order, Product, Profile
from .services import OrderError, create_order
from .tokens import make_token, user_from_token

MIN_PASSWORD_LENGTH = 6
MAX_PHOTO_BYTES = 4 * 1024 * 1024
MAX_BIO_LENGTH = 1000
ALLOWED_PHOTO_FORMATS = {"JPEG", "PNG", "WEBP"}


def error(message, status=400, details=None):
    body = {"error": message}
    if details:
        body["details"] = details
    return JsonResponse(body, status=status, json_dumps_params={"ensure_ascii": False})


def ok(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def read_json(request):
    """بدنه‌ی JSON را می‌خواند؛ اگر خراب بود None."""
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def token_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        user = user_from_token(token.strip()) if scheme.lower() == "bearer" else None
        if user is None:
            return error("ورود لازم است یا توکن منقضی شده است.", status=401)
        request.api_user = user
        return view(request, *args, **kwargs)

    return wrapper


def product_to_dict(request, product):
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "category": product.category.name,
        "category_id": product.category_id,
        "price": product.price,
        "stock": product.stock_qty,
        "in_stock": product.stock_qty > 0,
        "description": product.description,
        "image": request.build_absolute_uri(product.image.url) if product.image else None,
    }


@require_http_methods(["GET"])
def product_list(request):
    """?q=جستجو  &category=<id یا نام>  &in_stock=1"""
    qs = Product.objects.with_stock().select_related("category").filter(is_active=True)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))

    category = request.GET.get("category", "").strip()
    if category:
        if category.isdigit():
            qs = qs.filter(category_id=int(category))
        else:
            qs = qs.filter(category__name=category)

    if request.GET.get("in_stock") == "1":
        qs = qs.filter(stock_qty__gt=0)

    results = [product_to_dict(request, p) for p in qs.order_by("id")]
    return ok({"count": len(results), "results": results})


@require_http_methods(["GET"])
def product_detail(request, pk):
    product = (
        Product.objects.with_stock()
        .select_related("category")
        .filter(pk=pk, is_active=True)
        .first()
    )
    if product is None:
        return error("کالا پیدا نشد.", status=404)
    return ok(product_to_dict(request, product))


@require_http_methods(["GET"])
def category_list(request):
    results = [{"id": c.id, "name": c.name} for c in Category.objects.all()]
    return ok({"count": len(results), "results": results})


def auth_payload(user):
    return {
        "token": make_token(user),
        "username": user.username,
        "email": user.email,
        "user_id": user.pk,
    }


@csrf_exempt
@require_http_methods(["POST"])
def register(request):
    data = read_json(request)
    if data is None:
        return error("بدنه‌ی درخواست باید JSON معتبر باشد.")

    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    email = str(data.get("email", "")).strip()

    if not username or not password:
        return error("username و password الزامی است.")
    if len(password) < MIN_PASSWORD_LENGTH:
        return error(f"رمز عبور باید حداقل {MIN_PASSWORD_LENGTH} حرف باشد.")
    if email:
        try:
            validate_email(email)
        except ValidationError:
            return error("ایمیل معتبر نیست.")

    User = get_user_model()
    try:
        user = User.objects.create_user(username=username, email=email, password=password)
    except IntegrityError:
        return error("این نام کاربری قبلاً ثبت شده است.", status=409)

    return ok(auth_payload(user), status=201)


@csrf_exempt
@require_http_methods(["POST"])
def login(request):
    data = read_json(request)
    if data is None:
        return error("بدنه‌ی درخواست باید JSON معتبر باشد.")

    user = authenticate(
        request,
        username=str(data.get("username", "")).strip(),
        password=str(data.get("password", "")),
    )
    if user is None:
        return error("نام کاربری یا رمز عبور اشتباه است.", status=401)

    return ok(auth_payload(user))


def order_to_dict(order):
    items = [
        {
            "product_id": i.product_id,
            "name": i.product.name,
            "quantity": i.quantity,
            "unit_price": i.unit_price,
            "line_total": i.line_total,
        }
        for i in order.items.all()
    ]
    return {
        "id": order.id,
        "created_at": order.created_at.isoformat(),
        "items": items,
        "total_price": sum(i["line_total"] for i in items),
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def orders(request):
    """POST: {"items": [{"product_id": 1, "quantity": 2}]}  |  GET: سفارش‌های من"""
    if request.method == "GET":
        mine = (
            Order.objects.filter(user=request.api_user)
            .prefetch_related("items__product")
        )
        results = [order_to_dict(o) for o in mine]
        return ok({"count": len(results), "results": results})

    data = read_json(request)
    if data is None:
        return error("بدنه‌ی درخواست باید JSON معتبر باشد.")

    try:
        order = create_order(request.api_user, data.get("items"))
    except OrderError as exc:
        return error(exc.message, details=exc.details)

    order = Order.objects.prefetch_related("items__product").get(pk=order.pk)
    return ok(order_to_dict(order), status=201)


# ---------------------------------------------------------------- پروفایل

def profile_to_dict(request, user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return {
        "username": user.username,
        "email": user.email,
        "bio": profile.bio,
        "photo": request.build_absolute_uri(profile.photo.url) if profile.photo else None,
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
@token_required
def profile(request):
    """GET: پروفایل من  |  POST: {"bio": "..."} برای ذخیره‌ی بیو"""
    user = request.api_user

    if request.method == "POST":
        data = read_json(request)
        if data is None or "bio" not in data:
            return error('بدنه‌ی درخواست باید JSON با کلید "bio" باشد.')
        bio = str(data["bio"]).strip()
        if len(bio) > MAX_BIO_LENGTH:
            return error(f"بیو حداکثر {MAX_BIO_LENGTH} حرف می‌تواند باشد.")
        record, _ = Profile.objects.get_or_create(user=user)
        record.bio = bio
        record.save(update_fields=["bio"])

    return ok(profile_to_dict(request, user))


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def profile_photo(request):
    """بدنه‌ی درخواست خود بایت‌های عکس (JPEG/PNG/WEBP) است، نه JSON.
    سرور عکس را بررسی، به حداکثر ۵۱۲ پیکسل کوچک و دوباره ذخیره می‌کند."""
    body = request.body
    if not body:
        return error("عکسی ارسال نشده است.")
    if len(body) > MAX_PHOTO_BYTES:
        return error("حجم عکس بیشتر از ۴ مگابایت است.", status=413)

    try:
        Image.open(BytesIO(body)).verify()
        image = Image.open(BytesIO(body))
        if image.format not in ALLOWED_PHOTO_FORMATS:
            return error("فقط عکس JPEG، PNG یا WEBP قبول است.")
        image = image.convert("RGB")
    except Exception:  # noqa: BLE001 - هر فایل خراب یا غیرعکس
        return error("فایل ارسالی عکس معتبری نیست.")

    image.thumbnail((512, 512))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=88)

    user = request.api_user
    record, _ = Profile.objects.get_or_create(user=user)
    if record.photo:
        record.photo.delete(save=False)  # عکس قبلی پاک شود تا فایل اضافه نماند
    record.photo.save(f"user{user.pk}.jpg", ContentFile(buffer.getvalue()), save=True)

    return ok(profile_to_dict(request, user))


# ---------------------------------------------------------------- علاقه‌مندی

@require_http_methods(["GET"])
@token_required
def favorites(request):
    ids = list(
        Favorite.objects.filter(user=request.api_user).values_list("product_id", flat=True)
    )
    return ok({"product_ids": ids})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def favorite_toggle(request, pk):
    """اگر کالا در علاقه‌مندی‌ها نبود اضافه، وگرنه حذف می‌شود."""
    product = Product.objects.filter(pk=pk, is_active=True).first()
    if product is None:
        return error("کالا پیدا نشد.", status=404)

    favorite, created = Favorite.objects.get_or_create(user=request.api_user, product=product)
    if not created:
        favorite.delete()
    return ok({"product_id": pk, "favorite": created})
