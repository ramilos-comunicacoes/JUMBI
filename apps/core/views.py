from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST

from apps.partners.services import active_partner_for_user

from .forms import EmailAuthenticationForm, OrganizationRegistrationForm, UserAccessProvisionForm
from .models import AuditLog, Membership, Organization, User
from .navigation import SEGMENT_APPS, control_shell_context
from .services import active_organization, available_organizations
from .super_apps import SUPER_APPS


BUSINESS_DESTINATIONS = {
    Organization.BusinessType.OFFICE: "office:workspace",
}


def organization_destination(organization):
    return BUSINESS_DESTINATIONS.get(organization.business_type)


class UserLoginView(LoginView):
    template_name = "core/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if not user.is_superuser:
            organization = Organization.objects.filter(
                memberships__user=user,
                memberships__is_active=True,
                status=Organization.Status.ACTIVE,
                business_type__in=BUSINESS_DESTINATIONS,
            ).order_by("memberships__created_at", "name").first()
            if organization is None and active_partner_for_user(user) is not None:
                return super().form_valid(form)
            if organization is None:
                form.add_error(None, "Sua conta ainda não possui um ambiente Jumbi Jurídico ativo ou portal de parceiros ativo. Fale com o administrador.")
                return self.form_invalid(form)
            self.request.session["active_organization_id"] = organization.pk
        return super().form_valid(form)

    def get_success_url(self):
        if self.request.user.is_superuser:
            return reverse("core:control-panel")
        organization = active_organization(self.request)
        destination = organization_destination(organization) if organization else None
        if destination:
            return reverse(destination)
        if active_partner_for_user(self.request.user):
            return reverse("partners:portal")
        return reverse("pages:home")


class UserLogoutView(LogoutView):
    next_page = reverse_lazy("pages:home")


class UserPasswordChangeView(PasswordChangeView):
    template_name = "core/password_change.html"
    success_url = reverse_lazy("core:dashboard")


def signup(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    messages.info(request, "O acesso ao Jumbi é criado pela nossa equipe após o contato inicial.")
    return redirect("pages:demo-request")


def access(request):
    return redirect("core:login")


def segment_login(request, segment):
    if segment not in SUPER_APPS:
        raise Http404("Segmento não encontrado.")
    return redirect("core:login")


@login_required
def dashboard(request):
    if request.user.is_superuser:
        return redirect("core:control-panel")
    if active_organization(request) is None and active_partner_for_user(request.user):
        return redirect("partners:portal")
    organization = active_organization(request)
    if organization is None:
        raise PermissionDenied("Sua conta não possui uma organização ativa.")
    destination = organization_destination(organization)
    if destination is None:
        raise PermissionDenied("O produto desta organização ainda não está habilitado.")
    return redirect(destination)


@login_required
@require_POST
def switch_organization(request):
    organization = available_organizations(request.user).filter(pk=request.POST.get("organization_id")).first()
    if organization is None:
        raise PermissionDenied("Organização indisponível para esta conta.")
    request.session["active_organization_id"] = organization.pk
    return redirect("core:dashboard")


@login_required
def control_panel(request, section="overview"):
    if not request.user.is_superuser:
        raise PermissionDenied("Este painel é restrito a administradores da plataforma.")
    shell_context = control_shell_context(section)
    if shell_context is None:
        raise Http404("Seção administrativa não encontrada.")

    organization_form = OrganizationRegistrationForm(prefix="organization")
    access_form = UserAccessProvisionForm(prefix="access")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "organization":
            organization_form = OrganizationRegistrationForm(request.POST, prefix="organization")
            if organization_form.is_valid():
                organization = organization_form.save()
                messages.success(request, f"{organization.name} foi cadastrada com sucesso.")
                return redirect("core:control-section", section="organizations")
        elif action == "access":
            access_form = UserAccessProvisionForm(request.POST, prefix="access")
            if access_form.is_valid():
                user = access_form.save()
                messages.success(request, f"Acesso de {user.email} criado e vinculado ao sistema selecionado.")
                return redirect("core:control-section", section="accesses")

    organizations = Organization.objects.filter(
        business_type=Organization.BusinessType.OFFICE,
    ).prefetch_related("memberships").order_by("-created_at")
    memberships = Membership.objects.select_related("user", "organization").order_by(
        "organization__business_type", "organization__name", "user__email"
    ).filter(organization__business_type=Organization.BusinessType.OFFICE)
    context = {
        **shell_context,
        "organization_form": organization_form,
        "access_form": access_form,
        "organizations": organizations,
        "memberships": memberships,
        "audit_logs": AuditLog.objects.select_related("organization", "actor")[:100],
        "users_count": User.objects.count(),
        "organizations_count": organizations.count(),
        "active_accesses_count": memberships.filter(is_active=True).count(),
        "segment_apps": {"office": SEGMENT_APPS["office"]},
    }
    return render(request, "core/control_panel.html", context)
