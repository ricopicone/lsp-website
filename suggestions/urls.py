from django.urls import path

from . import views

app_name = "suggestions"

urlpatterns = [
    path("", views.suggest_page, name="suggest"),
    path("submit/", views.submit, name="submit"),
    path("mine/", views.mine, name="mine"),
    path("<int:pk>/screenshot/", views.screenshot_download, name="screenshot"),
]
