import hashlib
import secrets
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView, redirect_to_login
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST, require_http_methods

from .models import Membership, Organization, User, WorkspaceInvitation
from .workspace_forms import LoginForm, SignupForm, InvitationForm, InvitationAcceptForm


def home(request):
    return render(request, "public/home.html")


def health(request):
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok", "application": "JUMBI"})


class WorkspaceLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        if getattr(self.request, 'membership', None) and self.request.membership.role == 'client':
            return reverse('portal:home')
        if Membership.objects.filter(user=self.request.user, organization_id=self.request.session.get('active_organization_id'), role='client', is_active=True).exists():
            return reverse('portal:home')
        if self.get_redirect_url():
            return self.get_redirect_url()
        if self.request.user.is_superuser:
            return reverse("core:platform")
        from .preferences import office_preferences
        member = Membership.objects.filter(user=self.request.user, organization_id=self.request.session.get("active_organization_id"), is_active=True).select_related("organization").first()
        return reverse("legal:" + office_preferences(member.organization if member else None)["landing_page"])

    def form_valid(self, form):
        user = form.get_user()
        membership = Membership.objects.filter(
            user=user, is_active=True, organization__status="active", organization__business_type="office"
        ).first()
        if not membership and not user.is_superuser and not self.get_redirect_url().startswith("/convite/"):
            form.add_error(None, "Sua conta está sem um escritório ativo. Solicite um convite ao responsável pelo escritório.")
            return self.form_invalid(form)
        if membership:
            self.request.session["active_organization_id"] = membership.organization_id
        return super().form_valid(form)


class WorkspaceLogoutView(LogoutView):
    next_page = reverse_lazy("core:home")


class WorkspacePasswordChangeView(PasswordChangeView):
    template_name = "registration/password_change.html"
    success_url = reverse_lazy("legal:dashboard")

    def form_valid(self, form):
        messages.success(self.request, "Senha alterada com sucesso.")
        return super().form_valid(form)


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated and request.organization:
        return redirect("legal:dashboard")
    form = SignupForm(request.POST if request.method == "POST" else None, initial={"plan": request.GET.get("plano", "start")})
    if request.method == "POST" and form.is_valid():
        source_ip = request.META.get("REMOTE_ADDR", "")
        # Gunicorn is bound to loopback; Nginx overwrites X-Real-IP in our vhost.
        from django.conf import settings
        if not settings.DEBUG and source_ip in {"127.0.0.1", "::1"}:
            source_ip = request.META.get("HTTP_X_REAL_IP", source_ip)
        rate_key = "signup:" + hashlib.sha256(source_ip.encode()).hexdigest()
        if cache.get(rate_key, 0) >= 10:
            form.add_error(None, "Limite temporário de cadastros atingido. Tente novamente em uma hora.")
        else:
            try:
                with transaction.atomic():
                    user = form.save()
                    organization = Organization.objects.create(
                        name=form.cleaned_data["organization_name"],
                        slug=f'{slugify(form.cleaned_data["organization_name"])[:100] or "escritorio"}-{secrets.token_hex(4)}',
                        business_type="office", contact_email=user.email,
                    )
                    Membership.objects.create(organization=organization, user=user, role="owner")
                    from apps.billing.models import OrganizationSubscription, SubscriptionEvent
                    subscription = OrganizationSubscription.objects.create(organization=organization, plan=form.cleaned_data["plan"])
                    SubscriptionEvent.objects.create(subscription=subscription, actor=user, description="Solicitação de contratação recebida pelo cadastro público. Aguardando ativação administrativa.")
                    from apps.legal.services import audit
                    audit(organization=organization, actor=user, action="workspace.created", description="Escritório criado por cadastro público.")
                cache.set(rate_key, cache.get(rate_key, 0) + 1, 3600)
                login(request, user, backend="apps.core.workspace_auth.EmailBackend")
                request.session["active_organization_id"] = organization.pk
                messages.success(request, "Cadastro recebido. Seu plano aguarda contratação e ativação pela administração.")
                return redirect("billing:subscription")
            except IntegrityError:
                form.add_error(None, "Não foi possível criar a conta. Confira os dados ou tente entrar com seu e-mail.")
    return render(request, "registration/signup.html", {"form": form})


def _manager(request):
    if not request.organization or not request.membership or request.membership.role not in {"owner", "manager"}:
        raise PermissionDenied("Esta área é reservada à gestão do escritório.")


@login_required
@require_http_methods(["GET", "POST"])
def team(request):
    _manager(request)
    form = InvitationForm(request.POST if request.method == "POST" else None, membership=request.membership)
    invite_url = request.session.pop("new_invitation_url", "")
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        if Membership.objects.filter(organization=request.organization, user__email__iexact=email, is_active=True).exists():
            form.add_error("email", "Esta pessoa já integra o escritório.")
        else:
            token = secrets.token_urlsafe(32)
            with transaction.atomic():
                WorkspaceInvitation.objects.filter(organization=request.organization, email__iexact=email, accepted_at__isnull=True, revoked_at__isnull=True).update(revoked_at=timezone.now())
                invitation = WorkspaceInvitation.objects.create(
                    organization=request.organization, email=email, role=form.cleaned_data["role"],
                    token_hash=hashlib.sha256(token.encode()).hexdigest(), invited_by=request.user,
                    expires_at=timezone.now() + timedelta(days=7),
                )
                from apps.legal.services import audit
                audit(organization=request.organization, actor=request.user, action="team.invited", description=f"Convite criado para {email} ({invitation.get_role_display()}).")
            request.session["new_invitation_url"] = request.build_absolute_uri(reverse("core:invitation", args=[token]))
            messages.success(request, "Convite criado. Compartilhe o link com a pessoa convidada; ele expira em 7 dias.")
            return redirect("core:team")
    members = Membership.objects.filter(organization=request.organization).select_related("user").order_by("-is_active", "user__first_name")
    invitations = WorkspaceInvitation.objects.filter(organization=request.organization, accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now())
    return render(request, "legal/team.html", {"form": form, "members": members, "invitations": invitations, "invite_url": invite_url, "page_title": "Equipe e acessos", "active_nav": "team"})


@login_required
@require_POST
def revoke_membership(request, pk):
    _manager(request)
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=request.organization.pk)
        member = get_object_or_404(Membership.objects.select_for_update(), pk=pk, organization=request.organization)
        if member.user_id == request.user.pk:
            raise PermissionDenied("Você não pode revogar seu próprio acesso nesta tela.")
        if member.role == "owner" and request.membership.role != "owner":
            raise PermissionDenied("Somente a direção pode revogar este acesso.")
        if member.role == "owner" and not Membership.objects.filter(organization=request.organization, role="owner", is_active=True).exclude(pk=pk).exists():
            raise PermissionDenied("O escritório precisa manter pelo menos um responsável da direção.")
        member.is_active = False
        member.save(update_fields=["is_active"])
        from apps.legal.services import audit
        audit(organization=request.organization, actor=request.user, action="team.revoked", description=f"Acesso revogado: {member.user.email}.")
    messages.success(request, "Acesso revogado. Os registros e o histórico foram preservados.")
    return redirect("core:team")


@login_required
@require_POST
def revoke_invitation(request, pk):
    _manager(request)
    invitation = get_object_or_404(WorkspaceInvitation, pk=pk, organization=request.organization)
    if invitation.role == "owner" and request.membership.role != "owner":
        raise PermissionDenied("Somente a direção pode revogar este convite.")
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at"])
    from apps.legal.services import audit
    audit(organization=request.organization, actor=request.user, action="team.invitation_revoked", description=f"Convite revogado para {invitation.email}.")
    messages.success(request, "Convite revogado.")
    return redirect("core:team")


@require_http_methods(["GET", "POST"])
def accept_invitation(request, token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    invitation = get_object_or_404(WorkspaceInvitation, token_hash=digest, organization__status="active", organization__business_type="office", accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now())
    existing_user = User.objects.filter(email__iexact=invitation.email).first()
    if request.user.is_authenticated and request.user.email.lower() != invitation.email.lower():
        raise PermissionDenied("Entre com a conta indicada no convite para aceitá-lo.")
    if existing_user and not request.user.is_authenticated:
        return redirect_to_login(request.path, login_url=reverse("core:login"))
    form = forms.Form(request.POST or None) if existing_user else InvitationAcceptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            from apps.billing.services import check_capacity
            from django.core.exceptions import ValidationError
            try:
                check_capacity(invitation.organization, "members", user=existing_user)
            except ValidationError as error:
                return render(request, "registration/error.html", {"code": 409, "message": " ".join(error.messages)}, status=409)
            invitation = get_object_or_404(WorkspaceInvitation.objects.select_for_update(), pk=invitation.pk, accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now(), organization__status="active")
            # Re-check the inviter's current authority; an old link cannot retain revoked power.
            inviter = Membership.objects.filter(organization=invitation.organization, user=invitation.invited_by, is_active=True).first()
            if not inviter or inviter.role not in {"owner", "manager"} or (invitation.role == "owner" and inviter.role != "owner"):
                raise PermissionDenied("O responsável pelo convite já não tem permissão para conceder este acesso.")
            user = existing_user
            if user is None:
                user = form.save(commit=False)
                user.email = invitation.email.lower()
                user.save()
            Membership.objects.update_or_create(organization=invitation.organization, user=user, defaults={"role": invitation.role, "is_active": True})
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=["accepted_at"])
            from apps.legal.services import audit
            audit(organization=invitation.organization, actor=user, action="team.accepted", description="Convite aceito e vínculo ativado.")
        login(request, user, backend="apps.core.workspace_auth.EmailBackend")
        request.session["active_organization_id"] = invitation.organization_id
        messages.success(request, "Convite aceito. Bem-vindo ao escritório.")
        return redirect("legal:dashboard")
    return render(request, "registration/invitation.html", {"form": form, "invitation": invitation})


@login_required
@require_POST
def switch_organization(request):
    try:
        organization_id = int(request.POST.get("organization_id", ""))
    except (TypeError, ValueError):
        raise Http404("Escritório não encontrado.") from None
    member = get_object_or_404(Membership, user=request.user, organization_id=organization_id, is_active=True, organization__status="active", organization__business_type="office")
    request.session["active_organization_id"] = member.organization_id
    return redirect("legal:dashboard")


@login_required
def audit_trail(request):
    _manager(request)
    from apps.legal.views import accessible_audit
    events = accessible_audit(request.user, request.organization, role=request.membership.role).select_related("actor").order_by("-created_at")
    page = Paginator(events, 50).get_page(request.GET.get("page"))
    return render(request, "legal/audit.html", {"events": page, "activity": page, "page_obj": page, "page_title": "Auditoria", "active_nav": "audit"})


@login_required
@require_http_methods(["GET", "POST"])
def customization(request):
    _manager(request)
    from .customization_forms import WorkspaceCustomizationForm
    from .preferences import NAV_CHOICES, office_preferences
    from apps.legal.services import audit
    org = request.organization
    form = WorkspaceCustomizationForm(request.POST if request.method == "POST" else None, request.FILES or None, instance=org)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            locked = Organization.objects.select_for_update().get(pk=org.pk)
            if request.POST.get("revision") != locked.updated_at.isoformat():
                form.add_error(None, "Outra pessoa atualizou as preferências. Recarregue esta página para conferir as alterações antes de salvar.")
            else:
                changed = [name for name in form.changed_data if name != "revision"]
                org = form.save()
                audit(organization=org, actor=request.user, action="organization.customized", obj=org,
                      description="Personalização atualizada: " + ", ".join(str(form.fields[name].label or name) for name in changed))
                messages.success(request, "Preferências salvas para este escritório.")
                return redirect("core:customization")
    prefs = office_preferences(org)
    order = form.cleaned_data.get("nav_order", prefs["nav_order"]) if form.is_bound and hasattr(form, "cleaned_data") else prefs["nav_order"]
    keys = list(dict.fromkeys([*order, *dict(NAV_CHOICES)]))
    return render(request, "core/customization.html", {
        "page_title": "Personalização do escritório", "active_nav": "customization",
        "form": form, "field_groups": form.field_groups(), "navigation_order": [(key, dict(NAV_CHOICES)[key]) for key in keys],
    })



def error403(request, exception=None):
    return render(request, "registration/error.html", {"code": 403, "message": "Sua conta não tem permissão para acessar este conteúdo."}, status=403)


def error404(request, exception=None):
    return render(request, "registration/error.html", {"code": 404, "message": "Este conteúdo não está disponível para sua conta ou não existe."}, status=404)


def error500(request):
    return render(request, "registration/error.html", {"code": 500, "message": "Não foi possível concluir a operação. Tente novamente em instantes."}, status=500)
