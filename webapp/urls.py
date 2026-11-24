from django.urls import path

from . import views

app_name = "webapp"

# Manzillar eski React frontend bilan bir xil, shuning uchun bot tugmalari o'zgarmaydi
urlpatterns = [
    path("", views.home, name="home"),
    path("auth/", views.auth, name="auth"),
    path("bot/", views.bot_redirect, name="bot"),
    path("test/<int:pk>/", views.subject_tests, name="subject"),
    path("register/", views.register, name="register"),
    path("profile/", views.profile, name="profile"),
    path("create_test/", views.create_option, name="create_option"),
    path("create_national/", views.create_national, name="create_national"),
    path("create_national/<int:pk>/", views.test_created, name="test_created"),
    path("create_dtm/", views.create_dtm, name="create_dtm"),
    path("create_dtm/<int:pk>/", views.dtm_created, name="dtm_created"),
    path("send_test/", views.send_test, name="send_test"),
    path("send_test/<int:pk>/", views.send_sheet, name="send_sheet"),
    path("start/<int:pk>/", views.start, name="start"),
    path("dtm/", views.dtm, name="dtm"),
    path("dtm/<int:pk>/", views.dtm_sheet, name="dtm_sheet"),
    # Kitob testlari (QR kod: ?startapp=test_<slug>)
    path("booktest/", views.booktest, name="booktest"),
    path("booktest/create/", views.booktest_create, name="booktest_create"),
    path("booktest/created/<slug:slug>/", views.booktest_created, name="booktest_created"),
    path("booktest/<slug:slug>/", views.booktest_sheet, name="booktest_sheet"),
]
