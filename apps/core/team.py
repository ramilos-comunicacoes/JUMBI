from django.core.exceptions import PermissionDenied
from django.db import transaction

from .forms import OrganizationMemberProvisionForm, OrganizationRoleForm
from .models import AuditLog, Membership, Organization, OrganizationRole
from .services import has_permission, require_permission


DEFAULT_ROLE_BLUEPRINTS = {
    Organization.BusinessType.OFFICE: (
        ("Sócio(a) diretor(a)", 10, Membership.Role.OWNER, "Direção estratégica e controle integral do escritório."),
        ("Gerente jurídico", 10, Membership.Role.MANAGER, "Coordenação da equipe, carteira e rotinas administrativas."),
        ("Advogado(a) / Analista", 60, Membership.Role.OPERATOR, "Execução jurídica e operacional."),
        ("Assistente", 80, Membership.Role.OPERATOR, "Apoio aos processos e à operação do escritório."),
        ("Consulta / Auditoria", 100, Membership.Role.VIEWER, "Acesso de leitura para acompanhamento e auditoria."),
    ),
    Organization.BusinessType.ENGINEERING: (
        ("Diretor(a) / CEO", 10, Membership.Role.OWNER, "Direção estratégica e controle integral da empresa."),
        ("Gerente de engenharia", 10, Membership.Role.MANAGER, "Gestão de obras, equipes, compras e resultados."),
        ("Engenheiro(a) / Arquiteto(a)", 60, Membership.Role.OPERATOR, "Execução técnica e acompanhamento de obras."),
        ("Técnico(a) / Assistente", 80, Membership.Role.OPERATOR, "Apoio técnico e operacional."),
        ("Consulta / Auditoria", 100, Membership.Role.VIEWER, "Acesso de leitura para acompanhamento e auditoria."),
    ),
    Organization.BusinessType.AGRO: (
        ("Proprietário(a) / Diretor(a)", 10, Membership.Role.OWNER, "Direção estratégica e controle integral da operação."),
        ("Gerente de fazenda", 10, Membership.Role.MANAGER, "Gestão das fazendas, equipes, compras e produção."),
        ("Agrônomo(a) / Encarregado(a)", 60, Membership.Role.OPERATOR, "Planejamento e execução das operações rurais."),
        ("Operador(a) / Assistente", 80, Membership.Role.OPERATOR, "Execução e registro das atividades de campo."),
        ("Consulta / Auditoria", 100, Membership.Role.VIEWER, "Acesso de leitura para acompanhamento e auditoria."),
    ),
}


@transaction.atomic
def ensure_default_roles(organization):
    Organization.objects.select_for_update().get(pk=organization.pk)
    if not OrganizationRole.objects.filter(organization=organization).exists():
        OrganizationRole.objects.bulk_create([
            OrganizationRole(
                organization=organization,
                name=name,
                hierarchy_level=level,
                permission_role=permission_role,
                description=description,
            )
            for name, level, permission_role, description in DEFAULT_ROLE_BLUEPRINTS.get(
                organization.business_type,
                DEFAULT_ROLE_BLUEPRINTS[Organization.BusinessType.OFFICE],
            )
        ])

    default_by_permission = {
        role.permission_role: role
        for role in OrganizationRole.objects.filter(organization=organization).order_by("hierarchy_level")
    }
    for membership in Membership.objects.filter(organization=organization, position__isnull=True):
        position = default_by_permission.get(membership.role)
        if position:
            membership.position = position
            membership.save(update_fields=["position"])


def team_management_context(request, organization):
    ensure_default_roles(organization)
    can_manage = has_permission(request.user, "core.manage_members", organization)
    role_form = OrganizationRoleForm(
        prefix="hierarchy",
        organization=organization,
        actor=request.user,
    )
    member_form = OrganizationMemberProvisionForm(
        prefix="member",
        organization=organization,
        actor=request.user,
    )
    saved = False
    success_message = ""

    if request.method == "POST" and request.POST.get("action") in {
        "hierarchy_role",
        "organization_member",
        "membership_status",
        "hierarchy_status",
    }:
        require_permission(request.user, "core.manage_members", organization)
        action = request.POST["action"]

        if action == "hierarchy_role":
            role_form = OrganizationRoleForm(
                request.POST,
                prefix="hierarchy",
                organization=organization,
                actor=request.user,
            )
            if role_form.is_valid():
                role = role_form.save()
                AuditLog.objects.create(
                    organization=organization,
                    actor=request.user,
                    action="core.organization_role.created",
                    metadata={"role_id": role.pk, "name": role.name, "level": role.hierarchy_level},
                )
                saved = True
                success_message = f"Cargo {role.name} adicionado à hierarquia."

        elif action == "organization_member":
            member_form = OrganizationMemberProvisionForm(
                request.POST,
                prefix="member",
                organization=organization,
                actor=request.user,
            )
            if member_form.is_valid():
                membership = member_form.save()
                AuditLog.objects.create(
                    organization=organization,
                    actor=request.user,
                    action="core.membership.created",
                    metadata={
                        "membership_id": membership.pk,
                        "user_email": membership.user.email,
                        "position": membership.position.name,
                    },
                )
                saved = True
                success_message = f"Login individual de {membership.user.email} criado com sucesso."

        elif action == "membership_status":
            membership = Membership.objects.filter(
                organization=organization,
                pk=request.POST.get("membership_id"),
            ).select_related("user").first()
            if membership is None:
                raise PermissionDenied("Vínculo não encontrado nesta organização.")
            if membership.user_id == request.user.id:
                raise PermissionDenied("Você não pode desativar o seu próprio acesso.")
            actor_membership = Membership.objects.filter(
                organization=organization,
                user=request.user,
                is_active=True,
            ).first()
            if (
                not request.user.is_superuser
                and actor_membership
                and actor_membership.role != Membership.Role.OWNER
                and membership.role == Membership.Role.OWNER
            ):
                raise PermissionDenied("Apenas a direção pode alterar outro acesso de direção.")
            membership.is_active = request.POST.get("is_active") == "true"
            membership.save(update_fields=["is_active"])
            AuditLog.objects.create(
                organization=organization,
                actor=request.user,
                action="core.membership.status_changed",
                metadata={"membership_id": membership.pk, "is_active": membership.is_active},
            )
            saved = True
            success_message = f"Acesso de {membership.user.email} atualizado."

        elif action == "hierarchy_status":
            role = OrganizationRole.objects.filter(
                organization=organization,
                pk=request.POST.get("role_id"),
            ).first()
            if role is None:
                raise PermissionDenied("Cargo não encontrado nesta organização.")
            actor_membership = Membership.objects.filter(
                organization=organization,
                user=request.user,
                is_active=True,
            ).first()
            if (
                not request.user.is_superuser
                and actor_membership
                and actor_membership.role != Membership.Role.OWNER
                and role.permission_role == Membership.Role.OWNER
            ):
                raise PermissionDenied("Apenas a direção pode alterar um cargo de direção.")
            role.is_active = request.POST.get("is_active") == "true"
            role.save(update_fields=["is_active"])
            AuditLog.objects.create(
                organization=organization,
                actor=request.user,
                action="core.organization_role.status_changed",
                metadata={"role_id": role.pk, "is_active": role.is_active},
            )
            saved = True
            success_message = f"Cargo {role.name} atualizado."

    return {
        "team_role_form": role_form,
        "team_member_form": member_form,
        "organization_roles": OrganizationRole.objects.filter(organization=organization).prefetch_related("memberships"),
        "organization_memberships": Membership.objects.filter(organization=organization)
        .select_related("user", "position", "reports_to__user", "reports_to__position")
        .order_by("position__hierarchy_level", "user__first_name", "user__email"),
        "can_manage_team": can_manage,
        "team_saved": saved,
        "team_success_message": success_message,
    }
