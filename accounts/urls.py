"""Public auth URLs — login, logout, signup, password reset, magic link, 2FA."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import ReplyToPasswordResetForm

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),

    # Password reset (Django built-in flow). Template names are passed
    # explicitly under the accounts/ namespace because django.contrib.admin
    # ships colliding registration/password_reset_*.html templates and loads
    # first. ReplyToPasswordResetForm adds Reply-To: SUPPORT_EMAIL.
    path(
        "password/reset/",
        auth_views.PasswordResetView.as_view(
            form_class=ReplyToPasswordResetForm,
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/email/password_reset_body.html",
            subject_template_name="accounts/email/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "password/reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

    # Passwordless sign-in (magic link).
    path("login/link/", views.magic_link_request, name="magic_link_request"),
    path("login/link/<str:token>/", views.magic_link_consume, name="magic_link_consume"),

    # Two-factor authentication (TOTP).
    path("2fa/setup/", views.twofactor_setup, name="twofactor_setup"),
    path("2fa/verify/", views.twofactor_verify, name="twofactor_verify"),
    path("2fa/recovery/", views.twofactor_recovery, name="twofactor_recovery"),
    path("2fa/disable/", views.twofactor_disable, name="twofactor_disable"),

    path("profile/", views.profile_edit, name="profile_edit"),
    path("advisor/", views.advisor_select, name="advisor_select"),
    path("email/change/", views.email_change, name="email_change"),
    path("email/confirm/<str:token>/", views.email_change_confirm, name="email_change_confirm"),
    path("timezone/", views.timezone_settings, name="timezone_settings"),
    path("timezone/from-browser/",
         views.set_timezone_from_browser,
         name="set_timezone_from_browser"),
]
