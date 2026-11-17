# ⚙️ BlubrryMarket - Django Backend

این مخزن شامل کدهای سمت سرور (Backend) سیستم انبارداری BlubrryMarket است که با فریم‌ورک قدرتمند **Django** توسعه یافته است. این بخش وظیفه مدیریت دیتابیس، احراز هویت کاربران و ارائه API برای کلاینت دسکتاپ را بر عهده دارد.

## 🚀 ویژگی‌های بک‌اند
- توسعه‌یافته بر پایه معماری MVT جنگو.
- آماده‌سازی شده برای دیپلوی روی سرویس‌های ابری مانند PythonAnywhere (تنظیم `ALLOWED_HOSTS`).
- مدیریت امن متغیرهای محیطی برای کلیدهای حساس (SECRET_KEY).
- سیستم مدیریت یکپارچه پنل ادمین برای کنترل موجودی انبار.

## 🛠 تکنولوژی‌ها
- **Backend:** Python, Django
- **Database:** SQLite (قابل ارتقا به PostgreSQL در محیط پروداکشن)

## 💻 راهنمای اجرا
ابتدا مخزن را کلون کرده و پیش‌نیازها را نصب کنید:
```bash
pip install -r requirements.txt





python manage.py migrate
python manage.py runserver





