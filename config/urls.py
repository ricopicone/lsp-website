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
from django.views.generic import RedirectView

from accounts import views as _account_views
from content import views as _content_views
from core import staff as _staff_views
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
    # Listed before the <academic_year> catch-all so "proposals" wins.
    path("program-admin/proposals/", _event_views.program_admin_proposals,
         name="program_admin_proposals"),
    path("program-admin/proposals/<int:pk>/decide/",
         _event_views.seminar_proposal_decide, name="seminar_proposal_decide"),
    path("propose-seminar/", _event_views.seminar_propose, name="seminar_propose"),
    path("propose-seminar/<int:pk>/edit/", _event_views.seminar_proposal_edit,
         name="seminar_proposal_edit"),
    path("program-admin/<str:academic_year>/",
         _event_views.program_admin_detail,
         name="program_admin_detail"),
    path("program-admin/<str:academic_year>/events/new/",
         _event_views.program_admin_event_new,
         name="program_admin_event_new"),
    path("program-admin/<str:academic_year>/events/<slug:slug>/edit/",
         _event_views.program_admin_event_edit,
         name="program_admin_event_edit"),
    path("admin-tools/", _staff_views.home, name="admin_tools"),
    # Back-compat: the hub used to live at /staff/.
    path("staff/", RedirectView.as_view(pattern_name="admin_tools", permanent=False)),
    path("admin-tools/docs/<slug:slug>/", _staff_views.doc, name="staff_doc"),
    path("admin-tools/board/", _staff_views.board_admin, name="board_admin"),
    path("admin-tools/board/membership/", _staff_views.board_membership_admin,
         name="board_membership_admin"),
    path("admin-tools/assistant/", _staff_views.admin_assistant_admin,
         name="admin_assistant_admin"),
    path("admin-tools/web-coordinator/", _staff_views.web_coordinator_admin,
         name="web_coordinator_admin"),
    path("admin-tools/web-developer/", _staff_views.web_developer_admin,
         name="web_developer_admin"),
    path("admin-tools/aphorisms/", _staff_views.aphorism_list, name="staff_aphorisms"),
    path("admin-tools/aphorisms/new/", _staff_views.aphorism_create, name="staff_aphorism_new"),
    path("admin-tools/aphorisms/<int:pk>/edit/", _staff_views.aphorism_edit,
         name="staff_aphorism_edit"),
    path("admin-tools/aphorisms/<int:pk>/delete/", _staff_views.aphorism_delete,
         name="staff_aphorism_delete"),
    path("admin-tools/aphorisms/<int:pk>/toggle/", _staff_views.aphorism_toggle,
         name="staff_aphorism_toggle"),
    path("events/", include("events.urls")),
    path("documents/", include("documents.urls")),
    path("works/", include("works.urls")),
    path("parletre/", include("parletre.urls")),
    path("groups/", include("workgroups.urls")),
    path("cartels/", include("cartels.urls")),
    path("working-groups/", include("workinggroups.urls")),
    path("committees/", include("committees.urls")),
    path("", include("admissions.urls")),
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
