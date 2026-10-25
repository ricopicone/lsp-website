"""Turn a Stripe outage at Checkout into a message, not a server error."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .stripe_checkout import CheckoutUnavailable


class CheckoutUnavailableMiddleware:
    """Every Pay button posts to a view that opens Stripe Checkout; when
    Stripe errors, send the member back where they pressed it (task #820)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, CheckoutUnavailable):
            return None
        messages.error(
            request,
            "We couldn't reach the payment service, so nothing was charged. "
            "Please try again in a few minutes.",
        )
        back = request.META.get("HTTP_REFERER", "")
        if not url_has_allowed_host_and_scheme(
            back, allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            back = "/"
        return redirect(back)
