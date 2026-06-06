from django.urls import path

from . import views, voice

urlpatterns = [
    path("health", views.health),
    path("chat", views.chat),
    path("slots", views.slots),
    path("book", views.book),
    path("voice/token", voice.voice_token),
]
