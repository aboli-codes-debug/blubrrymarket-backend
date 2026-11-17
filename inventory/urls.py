from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("report/", views.stock_report, name="report"),
]
