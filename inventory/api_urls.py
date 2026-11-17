from django.urls import path

from . import api

urlpatterns = [
    path("products/", api.product_list),
    path("products/<int:pk>/", api.product_detail),
    path("categories/", api.category_list),
    path("register/", api.register),
    path("login/", api.login),
    path("orders/", api.orders),
    path("profile/", api.profile),
    path("profile/photo/", api.profile_photo),
    path("favorites/", api.favorites),
    path("favorites/<int:pk>/", api.favorite_toggle),
]
