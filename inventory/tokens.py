"""توکن ورود اپ دسکتاپ: امضاشده با SECRET_KEY، بدون جدول اضافه، با انقضا."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing

SALT = "anbar-api-token"


def make_token(user):
    return signing.dumps({"uid": user.pk}, salt=SALT)


def user_from_token(token):
    """کاربر را برمی‌گرداند؛ اگر توکن نامعتبر/منقضی بود None."""
    try:
        data = signing.loads(token, salt=SALT, max_age=settings.API_TOKEN_MAX_AGE)
    except signing.BadSignature:  # شامل SignatureExpired
        return None
    User = get_user_model()
    try:
        user = User.objects.get(pk=data["uid"])
    except (User.DoesNotExist, KeyError):
        return None
    return user if user.is_active else None
