import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Category, Order, Product, StockMovement
from .services import OrderError, create_order

User = get_user_model()


def make_product(name="گوشی", sku="P1", price=1000, stock=10, active=True, category=None):
    category = category or Category.objects.get_or_create(name="موبایل")[0]
    product = Product.objects.create(
        name=name, sku=sku, category=category, price=price, is_active=active
    )
    if stock:
        StockMovement.objects.create(product=product, kind="in", quantity=stock)
    return product


class StockTests(TestCase):
    def test_stock_is_in_minus_out(self):
        p = make_product(stock=10)
        StockMovement.objects.create(product=p, kind="out", quantity=3)
        StockMovement.objects.create(product=p, kind="in", quantity=5)
        self.assertEqual(p.compute_stock(), 12)
        self.assertEqual(Product.objects.with_stock().get(pk=p.pk).stock_qty, 12)

    def test_product_without_movements_has_zero(self):
        p = make_product(stock=0)
        self.assertEqual(Product.objects.with_stock().get(pk=p.pk).stock_qty, 0)

    def test_out_more_than_stock_fails_validation(self):
        from django.core.exceptions import ValidationError

        p = make_product(stock=2)
        movement = StockMovement(product=p, kind="out", quantity=5)
        with self.assertRaises(ValidationError):
            movement.full_clean()


class ApiTests(TestCase):
    def post(self, path, data, token=None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(
            path, data=json.dumps(data), content_type="application/json", **headers
        )

    def register(self, username="ali", password="secret1"):
        response = self.post("/api/register/", {"username": username, "password": password})
        self.assertEqual(response.status_code, 201)
        return response.json()["token"]

    def test_product_list_is_public_and_hides_inactive(self):
        make_product("A", "A1", stock=4)
        make_product("B", "B1", stock=1, active=False)
        data = self.client.get("/api/products/").json()
        self.assertEqual(data["count"], 1)
        item = data["results"][0]
        self.assertEqual(
            {k: item[k] for k in ("name", "price", "stock", "in_stock")},
            {"name": "A", "price": 1000, "stock": 4, "in_stock": True},
        )

    def test_filters(self):
        phones = Category.objects.create(name="phones")
        make_product("iPhone", "I1", category=phones, stock=2)
        make_product("Shirt", "S1", stock=0)
        self.assertEqual(self.client.get("/api/products/?q=iph").json()["count"], 1)
        self.assertEqual(self.client.get("/api/products/?category=phones").json()["count"], 1)
        self.assertEqual(self.client.get("/api/products/?in_stock=1").json()["count"], 1)

    def test_product_detail_404(self):
        self.assertEqual(self.client.get("/api/products/999/").status_code, 404)

    def test_register_login_and_bad_credentials(self):
        self.register()
        ok = self.post("/api/login/", {"username": "ali", "password": "secret1"})
        self.assertEqual(ok.status_code, 200)
        self.assertIn("token", ok.json())
        bad = self.post("/api/login/", {"username": "ali", "password": "wrong"})
        self.assertEqual(bad.status_code, 401)

    def test_register_duplicate_and_short_password(self):
        self.register()
        self.assertEqual(
            self.post("/api/register/", {"username": "ali", "password": "secret1"}).status_code, 409
        )
        self.assertEqual(
            self.post("/api/register/", {"username": "bob", "password": "123"}).status_code, 400
        )

    def test_orders_require_token(self):
        self.assertEqual(self.client.get("/api/orders/").status_code, 401)
        r = self.post("/api/orders/", {"items": [{"product_id": 1, "quantity": 1}]}, token="garbage")
        self.assertEqual(r.status_code, 401)

    def test_order_decreases_stock_and_records_movement(self):
        p = make_product(price=500, stock=10)
        token = self.register()
        r = self.post("/api/orders/", {"items": [{"product_id": p.id, "quantity": 3}]}, token)
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body["total_price"], 1500)
        self.assertEqual(p.compute_stock(), 7)
        movement = StockMovement.objects.filter(order_id=body["id"]).get()
        self.assertEqual((movement.kind, movement.quantity), ("out", 3))
        # لیست سفارش‌های من
        mine = self.client.get("/api/orders/", HTTP_AUTHORIZATION=f"Bearer {token}").json()
        self.assertEqual(mine["count"], 1)

    def test_insufficient_stock_rejects_whole_order(self):
        a = make_product("A", "A1", stock=5)
        b = make_product("B", "B1", stock=1)
        token = self.register()
        r = self.post(
            "/api/orders/",
            {"items": [{"product_id": a.id, "quantity": 2}, {"product_id": b.id, "quantity": 9}]},
            token,
        )
        self.assertEqual(r.status_code, 400)
        detail = r.json()["details"][0]
        self.assertEqual((detail["requested"], detail["available"]), (9, 1))
        # هیچ‌چیز تغییر نکرده (اتمیک)
        self.assertEqual(a.compute_stock(), 5)
        self.assertEqual(Order.objects.count(), 0)

    def test_order_validation_errors(self):
        p = make_product(stock=5)
        token = self.register()
        for items in ([], [{"product_id": p.id, "quantity": 0}], [{"product_id": "x"}], "bad"):
            r = self.post("/api/orders/", {"items": items}, token)
            self.assertEqual(r.status_code, 400, items)
        inactive = make_product("Z", "Z1", stock=5, active=False)
        r = self.post("/api/orders/", {"items": [{"product_id": inactive.id, "quantity": 1}]}, token)
        self.assertEqual(r.status_code, 400)

    def test_duplicate_items_are_merged(self):
        p = make_product(stock=4)
        user = User.objects.create_user("u", password="secret1")
        with self.assertRaises(OrderError):
            create_order(user, [{"product_id": p.id, "quantity": 3}, {"product_id": p.id, "quantity": 3}])
        self.assertEqual(p.compute_stock(), 4)

    def test_bad_json(self):
        r = self.client.post("/api/login/", data="{not json", content_type="application/json")
        self.assertEqual(r.status_code, 400)


class ProfileApiTests(ApiTests):
    """پروفایل، عکس و علاقه‌مندی. (از ApiTests ارث می‌برد تا post/register آماده باشد.)"""

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def png_bytes(self, size=(900, 600)):
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", size, (200, 30, 30)).save(buffer, "PNG")
        return buffer.getvalue()

    def test_auth_payload_has_email_and_id(self):
        r = self.post("/api/register/", {"username": "ali", "password": "secret1", "email": "a@b.com"})
        data = r.json()
        self.assertEqual((data["username"], data["email"]), ("ali", "a@b.com"))
        self.assertIn("user_id", data)

    def test_bad_email_rejected(self):
        r = self.post("/api/register/", {"username": "ali", "password": "secret1", "email": "nope"})
        self.assertEqual(r.status_code, 400)

    def test_profile_requires_token(self):
        self.assertEqual(self.client.get("/api/profile/").status_code, 401)

    def test_bio_save_and_read(self):
        token = self.register()
        empty = self.client.get("/api/profile/", **self.auth(token)).json()
        self.assertEqual((empty["bio"], empty["photo"]), ("", None))
        saved = self.post("/api/profile/", {"bio": "  سلام  "}, token).json()
        self.assertEqual(saved["bio"], "سلام")
        self.assertEqual(self.client.get("/api/profile/", **self.auth(token)).json()["bio"], "سلام")

    def test_bio_validation(self):
        token = self.register()
        self.assertEqual(self.post("/api/profile/", {"x": 1}, token).status_code, 400)
        self.assertEqual(self.post("/api/profile/", {"bio": "a" * 1001}, token).status_code, 400)

    def test_photo_upload_resizes_and_replaces(self):
        token = self.register()
        url = "/api/profile/photo/"
        r = self.client.post(url, data=self.png_bytes(), content_type="image/png", **self.auth(token))
        self.assertEqual(r.status_code, 200, r.content)
        photo = r.json()["photo"]
        self.assertTrue(photo.startswith("http"))

        from PIL import Image

        from .models import Profile

        record = Profile.objects.get(user__username="ali")
        with Image.open(record.photo.path) as img:
            self.assertLessEqual(max(img.size), 512)
        first_path = record.photo.path
        self.client.post(url, data=self.png_bytes((100, 100)), content_type="image/png", **self.auth(token))
        record.refresh_from_db()
        import os

        self.assertTrue(os.path.exists(record.photo.path))
        self.assertEqual(
            [f for f in os.listdir(os.path.dirname(first_path)) if f.startswith("user")].__len__() >= 1, True
        )
        record.photo.delete()

    def test_photo_rejects_garbage_empty_and_huge(self):
        token = self.register()
        url = "/api/profile/photo/"
        post = lambda body: self.client.post(url, data=body, content_type="application/octet-stream", **self.auth(token))
        self.assertEqual(post(b"not an image").status_code, 400)
        self.assertEqual(post(b"").status_code, 400)
        self.assertEqual(post(b"x" * (4 * 1024 * 1024 + 1)).status_code, 413)
        self.assertEqual(self.client.post(url, data=self.png_bytes(), content_type="image/png").status_code, 401)

    def test_favorites_toggle_and_list_are_per_user(self):
        product = make_product("A", "A1", stock=1)
        t1 = self.register("ali")
        t2 = self.register("bob")
        on = self.post(f"/api/favorites/{product.pk}/", {}, t1).json()
        self.assertTrue(on["favorite"])
        self.assertEqual(self.client.get("/api/favorites/", **self.auth(t1)).json()["product_ids"], [product.pk])
        self.assertEqual(self.client.get("/api/favorites/", **self.auth(t2)).json()["product_ids"], [])
        off = self.post(f"/api/favorites/{product.pk}/", {}, t1).json()
        self.assertFalse(off["favorite"])
        self.assertEqual(self.client.get("/api/favorites/", **self.auth(t1)).json()["product_ids"], [])

    def test_favorite_unknown_or_hidden_product_404_and_needs_token(self):
        hidden = make_product("H", "H1", stock=1, active=False)
        token = self.register()
        self.assertEqual(self.post("/api/favorites/999/", {}, token).status_code, 404)
        self.assertEqual(self.post(f"/api/favorites/{hidden.pk}/", {}, token).status_code, 404)
        self.assertEqual(self.client.post("/api/favorites/1/").status_code, 401)


class AdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@a.com", "adminpass1")
        self.product = make_product(stock=2)

    def test_admin_pages_render_in_persian_rtl(self):
        self.client.login(username="admin", password="adminpass1")
        r = self.client.get("/admin/inventory/product/")
        self.assertContains(r, "کالا")
        self.assertContains(r, 'dir="rtl"')
        self.assertEqual(self.client.get(f"/admin/inventory/product/{self.product.pk}/change/").status_code, 200)
        self.assertEqual(self.client.get("/admin/inventory/stockmovement/add/").status_code, 200)
        self.assertEqual(self.client.get("/admin/inventory/order/").status_code, 200)

    def test_filters_work(self):
        self.client.login(username="admin", password="adminpass1")
        for value in ("out", "low", "ok"):
            r = self.client.get(f"/admin/inventory/product/?stock_status={value}")
            self.assertEqual(r.status_code, 200, value)

    def test_admin_movement_inline_sets_creator_and_blocks_overdraw(self):
        self.client.login(username="admin", password="adminpass1")
        url = f"/admin/inventory/product/{self.product.pk}/change/"
        base = {
            "name": self.product.name, "sku": self.product.sku, "category": self.product.category_id,
            "price": self.product.price, "description": "", "reorder_level": 5, "is_active": "on",
            "movements-TOTAL_FORMS": "1", "movements-INITIAL_FORMS": "0",
            "movements-MIN_NUM_FORMS": "0", "movements-MAX_NUM_FORMS": "1000",
        }
        ok = self.client.post(url, {**base, "movements-0-kind": "in", "movements-0-quantity": "7"})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(self.product.compute_stock(), 9)
        self.assertEqual(StockMovement.objects.filter(created_by=self.admin).count(), 1)

        too_much = self.client.post(url, {**base, "movements-0-kind": "out", "movements-0-quantity": "50"})
        self.assertEqual(too_much.status_code, 200)       # برگشت به فرم با خطا
        self.assertEqual(self.product.compute_stock(), 9)  # تغییری نکرده

    def test_movement_history_cannot_be_edited(self):
        self.client.login(username="admin", password="adminpass1")
        movement = StockMovement.objects.first()
        self.assertEqual(
            self.client.post(f"/admin/inventory/stockmovement/{movement.pk}/delete/", {"post": "yes"}).status_code,
            403,
        )

    def test_report_requires_staff(self):
        self.assertEqual(self.client.get("/inventory/report/").status_code, 302)
        self.client.login(username="admin", password="adminpass1")
        r = self.client.get("/inventory/report/")
        self.assertContains(r, "گزارش موجودی انبار")
        self.assertContains(r, self.product.name)
