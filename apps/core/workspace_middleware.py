from .models import Membership


class OrganizationMiddleware:
    """Resolve the tenant from active membership, never from a user-supplied object ID."""

    def __init__(self, get_response):
        self.get_response = get_response

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
