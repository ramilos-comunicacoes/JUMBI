from django.conf import settings
from django.shortcuts import redirect, render
from .services import subscription_for


class SubscriptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not settings.JUMBI_ENFORCE_SUBSCRIPTIONS or not request.user.is_authenticated:
            return None
        match = request.resolver_match
        if not match:
            return None
        protected = match.namespace in {"legal", "performance", "contracts"} or (match.namespace == "core" and match.url_name in {"team", "audit", "revoke_member", "revoke_invitation"})
        # Portability remains available after expiration/suspension, subject to
        # the export view's existing membership and confidentiality checks.
        if not protected or match.url_name == "export":
            return None
        org = getattr(request, "organization", None)
        if org is None:
            return None
        subscription = subscription_for(org)
        if not subscription or not subscription.is_available:
            return redirect("billing:subscription")
        if (view_kwargs.get("module") in {"finance", "crm"} or match.namespace == "contracts") and not subscription.limits["advanced"]:
            return render(request, "billing/upgrade.html", {"page_title": "Recurso do plano Max", "active_nav": "subscription"}, status=403)
        return None
