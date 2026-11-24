from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .bot import webhook

router = DefaultRouter()
router.register(r"users", views.TelegramUserViewSet, basename="telegramuser")
router.register(r"subjects", views.SubjectViewSet, basename="subject")
router.register(r"tests", views.TestViewSet, basename="test")
router.register(r"requiredchannels", views.RequiredChannelViewSet, basename="requiredchannel")
router.register(r"booktests", views.BookTestViewSet, basename="booktest")
router.register(r"block-tests", views.BlockTestViewSet, basename="blocktest")

urlpatterns = [
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
    path("webhook/", webhook, name="webhook"),
]
