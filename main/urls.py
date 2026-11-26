from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .errors_api import ErrorDetailView, ErrorListView
from .bot import webhook

router = DefaultRouter()
router.register(r"users", views.TelegramUserViewSet, basename="telegramuser")
router.register(r"subjects", views.SubjectViewSet, basename="subject")
router.register(r"tests", views.TestViewSet, basename="test")
router.register(r"requiredchannels", views.RequiredChannelViewSet, basename="requiredchannel")
router.register(r"booktests", views.BookTestViewSet, basename="booktest")
router.register(r"block-tests", views.BlockTestViewSet, basename="blocktest")

urlpatterns = [
    path("api-auth/", include("rest_framework.urls")),
    path("webhook/", webhook, name="webhook"),
    # Xatolar API'si (ERROR_LOG_KEY kaliti bilan) — main/errors_api.py
    path("api/errors/", ErrorListView.as_view(), name="errors"),
    path("api/errors/<str:fingerprint>/", ErrorDetailView.as_view(), name="error_detail"),
    path("_errors/", ErrorListView.as_view()),  # eski manzil
    path("api/", include(router.urls)),
]
