from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("webhooks/stripe/", views.stripe_webhook, name="stripe_webhook"),
    path("transactions.csv", views.transactions_csv, name="transactions_csv"),
    path("<int:payment_id>/thanks/", views.payment_thanks, name="thanks"),
    path("<int:payment_id>/receipt/", views.receipt_download, name="receipt"),
]
