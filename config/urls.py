"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from accounts import views as _account_views
from content import views as _content_views
from events import views as _event_views
from payments import views as _payment_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("about/", _content_views.about, name="about"),
    path("directory/", _account_views.directory, name="directory"),
    path("directory/<slug:slug>/", _account_views.directory_detail, name="directory_detail"),
    path("find-an-analyst/", _account_views.find_an_analyst, name="find_an_analyst"),
    path("find-an-analyst/pins.json", _account_views.find_an_analyst_pins,
         name="find_an_analyst_pins"),
    path("program/", _event_views.program, name="program"),
    path("program-admin/", _event_views.program_admin_programs,
         name="program_admin_programs"),
    path("program-admin/help/", _event_views.program_admin_help,
         name="program_admin_help"),
    path("program-admin/<str:academic_year>/",
         _event_views.program_admin_detail,
         name="program_admin_detail"),
    path("program-admin/<str:academic_year>/events/new/",
         _event_views.program_admin_event_new,
         name="program_admin_event_new"),
    path("program-admin/<str:academic_year>/events/<slug:slug>/edit/",
         _event_views.program_admin_event_edit,
         name="program_admin_event_edit"),
    path("events/", include("events.urls")),
    path("documents/", include("documents.urls")),
    path("dues/", _payment_views.dues_pay, name="dues"),
    path("donate/", _payment_views.donate, name="donate"),
    path("tuition/", _payment_views.tuition_decision, name="tuition"),
    path("tuition/pay-in-full/", _payment_views.tuition_pay_in_full, name="tuition_pay_in_full"),
    path("tuition/setup-plan/", _payment_views.tuition_setup_plan, name="tuition_setup_plan"),
    path("tuition/installments/<int:installment_id>/pay/",
         _payment_views.tuition_pay_installment, name="tuition_pay_installment"),
    path("treasurer/", _payment_views.treasurer_dashboard, name="treasurer"),
    path("treasurer/tuition/", _payment_views.treasurer_tuition, name="treasurer_tuition"),
    path("treasurer/dues/", _payment_views.treasurer_dues, name="treasurer_dues"),
    path("treasurer/settings/", _payment_views.treasurer_settings, name="treasurer_settings"),
    path("treasurer/tuition/<int:user_id>/set-status/",
         _payment_views.treasurer_tuition_set_status,
         name="treasurer_tuition_set_status"),
    path("treasurer/tuition/<int:user_id>/record-payment/",
         _payment_views.treasurer_tuition_record_offline_payment,
         name="treasurer_tuition_record_offline_payment"),
    path("treasurer/dues/<int:user_id>/record-payment/",
         _payment_views.treasurer_dues_record_offline_payment,
         name="treasurer_dues_record_offline_payment"),
    path("treasurer/members/", _payment_views.treasurer_members, name="treasurer_members"),
    path("treasurer/members/<int:user_id>/",
         _payment_views.treasurer_member_detail,
         name="treasurer_member_detail"),
    path("treasurer/exports/", _payment_views.treasurer_exports, name="treasurer_exports"),
    path("treasurer/help/", _payment_views.treasurer_help, name="treasurer_help"),
    path("treasurer/payments/", _payment_views.treasurer_payments, name="treasurer_payments"),
    path("treasurer/payments/<int:payment_id>/refund/",
         _payment_views.treasurer_payment_refund,
         name="treasurer_payment_refund"),
    path("treasurer/payments/<int:payment_id>/apply-success/",
         _payment_views.treasurer_payment_apply_success,
         name="treasurer_payment_apply_success"),
    path("treasurer/payments/<int:payment_id>/resend-receipt/",
         _payment_views.treasurer_payment_resend_receipt,
         name="treasurer_payment_resend_receipt"),
    path("payments/", include("payments.urls")),
    path("", include("registrations.urls")),
    path("", include("core.urls")),
]
