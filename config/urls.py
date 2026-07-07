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
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from accounts import views as _account_views
from content import views as _content_views
from core import staff as _staff_views
from core import views as _core_views
from events import views as _event_views
from payments import views as _payment_views
from suggestions import views as _suggestion_views
from workgroups import views as _workgroups_views

urlpatterns = [
    # Readiness probe for the blue-green deploy flip (ops/deploy/). Mounted first
    # so nothing shadows it.
    path("healthz", _core_views.healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("about/", _content_views.about, name="about"),
    path("the-school/", _content_views.the_school, name="the_school"),
    # The Learning overview (nav tab) — scoped to learning kinds; the full
    # all-kinds overview stays at /groups/ (workgroups:list). Task #360 note.
    path("learning/", _workgroups_views.learning_list, name="learning"),
    # Public "Formation" content page. Lives under /about/ so it doesn't shadow
    # the member-facing formation hub at /formation/ (formation.urls).
    path("about/formation/", _content_views.page, {"slug": "formation"}, name="formation"),
    path("resources/", _content_views.page, {"slug": "resources"}, name="resources"),
    path("guides/", _content_views.guides_index_view, name="guides_index"),
    path("guides/<slug:slug>/", _content_views.guide_detail, name="guide_detail"),
    path("directory/", _account_views.directory, name="directory"),
    path("directory/availability/", _account_views.directory_availability,
         name="directory_availability"),
    path("directory/<slug:slug>/", _account_views.directory_detail, name="directory_detail"),
    path("find-an-analyst/", _account_views.find_an_analyst, name="find_an_analyst"),
    path("find-an-analyst/pins.json", _account_views.find_an_analyst_pins,
         name="find_an_analyst_pins"),
    path("program/", _event_views.program, name="program"),
    path("program/archive/", _event_views.program_archive, name="program_archive"),
    path("program/archive/<int:pk>/download/", _event_views.program_archive_download,
         name="program_archive_download"),
    path("program-admin/", _event_views.program_admin_programs,
         name="program_admin_programs"),
    path("program-admin/help/", _event_views.program_admin_help,
         name="program_admin_help"),
    # Listed before the <academic_year> catch-all so "proposals" wins.
    path("program-admin/proposals/", _event_views.program_admin_proposals,
         name="program_admin_proposals"),
    path("program-admin/proposals/<int:pk>/decide/",
         _event_views.proposal_decide, name="proposal_decide"),
    path("program-admin/changes/", _event_views.program_admin_changes,
         name="program_admin_changes"),
    path("program-admin/changes/<int:pk>/decide/",
         _event_views.change_request_decide, name="change_request_decide"),
    path("propose/", _event_views.propose_event, name="propose_event"),
    path("propose/mine/", _event_views.my_proposals, name="my_proposals"),
    path("propose/<int:pk>/edit/", _event_views.proposal_edit,
         name="proposal_edit"),
    path("propose/<int:pk>/submit/", _event_views.proposal_submit,
         name="proposal_submit"),
    path("propose/<int:pk>/delete/", _event_views.proposal_delete,
         name="proposal_delete"),
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
    path("admin-tools/board/appointments/", _staff_views.board_appointments,
         name="board_appointments"),
    path("admin-tools/board/committees/", _staff_views.board_committees,
         name="board_committees"),
    path("admin-tools/board/governance/", _staff_views.board_governance,
         name="board_governance"),
    path("admin-tools/meeting-of-analysts/", _staff_views.meeting_of_analysts_admin,
         name="meeting_of_analysts_admin"),
    path("admin-tools/assistant/", _staff_views.admin_assistant_admin,
         name="admin_assistant_admin"),
    path("admin-tools/web-coordinator/", _staff_views.web_coordinator_admin,
         name="web_coordinator_admin"),
    path("admin-tools/web-developer/", _staff_views.web_developer_admin,
         name="web_developer_admin"),
    path("admin-tools/web-developer/video/", _staff_views.video_upload_settings,
         name="video_upload_settings"),
    path("admin-tools/suggestions/", _suggestion_views.triage, name="suggestions_triage"),
    path("admin-tools/aphorisms/", _staff_views.aphorism_list, name="staff_aphorisms"),
    path("admin-tools/aphorisms/new/", _staff_views.aphorism_create, name="staff_aphorism_new"),
    path("admin-tools/aphorisms/<int:pk>/edit/", _staff_views.aphorism_edit,
         name="staff_aphorism_edit"),
    path("admin-tools/aphorisms/<int:pk>/delete/", _staff_views.aphorism_delete,
         name="staff_aphorism_delete"),
    path("admin-tools/aphorisms/<int:pk>/toggle/", _staff_views.aphorism_toggle,
         name="staff_aphorism_toggle"),
    # Video rooms: /events/<slug>/room/ and /groups/<slug>/room/. Mounted
    # before the events/groups includes so the room routes win.
    path("", include("video.urls")),
    path("events/", include("events.urls")),
    path("documents/", include("documents.urls")),
    path("works/", include("works.urls")),
    path("parletre/", include("parletre.urls")),
    path("notifications/", include("notifications.urls")),
    path("groups/", include("workgroups.urls")),
    path("cartels/", include("cartels.urls")),
    path("suggestions/", include("suggestions.urls")),
    path("devapi/", include("devapi.urls")),
    # Referral Coordinator surface (admin-tools/referrals/) + the clinician
    # respond page (referrals/<reference>/respond/).
    path("", include("referrals.urls")),
    # Applications Coordinator surface (admin-tools/availability/).
    path("", include("availability.urls")),
    path("working-groups/", include("workinggroups.urls")),
    path("committees/", include("committees.urls")),
    path("", include("admissions.urls")),
    path("", include("formation.urls")),
    path("dues/", _payment_views.dues_pay, name="dues"),
    path("donate/", _payment_views.donate, name="donate"),
    path("tuition/", _payment_views.tuition_decision, name="tuition"),
    path("tuition/pay-in-full/", _payment_views.tuition_pay_in_full, name="tuition_pay_in_full"),
    path("tuition/setup-plan/", _payment_views.tuition_setup_plan, name="tuition_setup_plan"),
    path("tuition/installments/<int:installment_id>/pay/",
         _payment_views.tuition_pay_installment, name="tuition_pay_installment"),
    path("payments/my/update/", _payment_views.my_payments_update,
         name="my_payments_update"),
    path("treasurer/", _payment_views.treasurer_dashboard, name="treasurer"),
    path("treasurer/tuition/", _payment_views.treasurer_tuition, name="treasurer_tuition"),
    path("treasurer/dues/", _payment_views.treasurer_dues, name="treasurer_dues"),
    path("treasurer/reconcile/", _payment_views.treasurer_reconcile,
         name="treasurer_reconcile"),
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

# Serve user-uploaded media from local disk during development. In production
# uploads live on S3 (served by their own absolute URLs), so this is a no-op
# there; gating on DEBUG keeps the dev-only route out of prod entirely.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
