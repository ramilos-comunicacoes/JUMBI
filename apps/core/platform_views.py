"""Platform overview, separate from organization-scoped legal operations."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from .models import Membership, Organization, User
from .platform_forms import OfficeConfigurationForm, OfficeCreationForm
from .platform_services import configure_office, create_office, require_platform_admin


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


@sensitive_post_parameters("password", "password_confirmation")
@login_required
@require_http_methods(["GET", "POST"])
def office_create(request):
    require_platform_admin(request.user)
    form = OfficeCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            office = create_office(actor=request.user, data=form.cleaned_data)
        except (ValidationError, IntegrityError):
            form.add_error(None, "Não foi possível criar a conta. Confira os dados e se o e-mail já foi cadastrado.")
        else:
            messages.success(request, f"Escritório {office.name} criado. O responsável pode entrar com o e-mail e a senha definidos.")
            return redirect("core:platform")
    return render(request, "platform/office_form.html", {
        "form": form, "page_title": "Criar escritório e acesso", "active_nav": "platform", "creating": True,
    })


@login_required
@require_http_methods(["GET", "POST"])
def office_configure(request, pk):
    require_platform_admin(request.user)
    office = get_object_or_404(Organization, pk=pk, business_type="office")
    form = OfficeConfigurationForm(request.POST or None, instance=office)
    if request.method == "POST" and form.is_valid():
        configure_office(actor=request.user, office_id=office.pk, data=form.cleaned_data)
        messages.success(request, "Dados e áreas de atuação atualizados.")
        return redirect("core:platform")
    return render(request, "platform/office_form.html", {
        "form": form, "page_title": f"Configurar {office.name}", "active_nav": "platform", "office": office,
    })
