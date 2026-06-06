from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    path("chat", views.chat),
    path("slots", views.slots),
    path("book", views.book),
]
