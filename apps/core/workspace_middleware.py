from .models import Membership


class OrganizationMiddleware:
    """Resolve the tenant from active membership, never from a user-supplied object ID."""

    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.membership or request.membership.role != 'client':
            return None
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import redirect
        match = request.resolver_match
        if not match:
            return None
        if request.user.is_superuser and (match.namespace in {'admin', 'platform'} or match.view_name == 'core:platform'):
            return None
        if match.view_name in {'legal:dashboard', 'core:dashboard'}:
            return redirect('portal:home')
        if match.namespace in {'portal', 'security'} or match.view_name in {
            'core:home', 'core:health', 'core:login', 'core:logout',
            'core:password_change', 'core:switch_organization', 'core:invitation',
        }:
            return None
        raise PermissionDenied('O perfil de cliente acessa somente seu portal e sua conta.')

    def __call__(self, request):
        request.organization = None
        request.membership = None
        if request.user.is_authenticated:
            memberships = Membership.objects.select_related("organization").filter(
                user=request.user, is_active=True,
                organization__status="active", organization__business_type="office",
            )
            selected = request.session.get("active_organization_id")
            membership = memberships.filter(organization_id=selected).first() if selected else None
            membership = membership or memberships.order_by("created_at").first()
            if membership:
                request.membership = membership
                request.organization = membership.organization
                request.session["active_organization_id"] = membership.organization_id
        response = self.get_response(request)
        if request.user.is_authenticated:
            response["Cache-Control"] = "private, no-store"
        return response
