"""Platform overview, separate from organization-scoped legal operations."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Membership, Organization, User


@login_required
@require_GET
def platform_dashboard(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied("Esta área é exclusiva da administração da plataforma.")

    office_scope = Organization.objects.filter(business_type="office")
    users = User.objects.filter(Q(memberships__organization__business_type="office") | Q(is_superuser=True)).distinct()
    organizations = office_scope.annotate(
        member_count=Count("memberships", filter=Q(memberships__is_active=True, memberships__user__is_active=True)),
    ).order_by("-created_at", "-pk")
    members = Membership.objects.filter(organization__business_type="office").select_related("user", "organization").order_by("-created_at", "-pk")
    return render(request, "platform/dashboard.html", {
        "page_title": "Controle da plataforma", "active_nav": "platform",
        "stats": {
            "organizations": office_scope.count(),
            "active_organizations": office_scope.filter(status="active").count(),
            "users": users.count(),
            "active_users": users.filter(is_active=True).count(),
        },
        "organizations_page": Paginator(organizations, 12).get_page(request.GET.get("offices")),
        "members_page": Paginator(members, 12).get_page(request.GET.get("members")),
    })
