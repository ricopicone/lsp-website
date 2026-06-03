"""Public auth URLs — login, logout, signup."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    path("profile/", views.profile_edit, name="profile_edit"),
    path("advisor/", views.advisor_select, name="advisor_select"),
    path("email/change/", views.email_change, name="email_change"),
    path("email/confirm/<str:token>/", views.email_change_confirm, name="email_change_confirm"),
    path("timezone/", views.timezone_settings, name="timezone_settings"),
    path("timezone/from-browser/",
         views.set_timezone_from_browser,
         name="set_timezone_from_browser"),
]
