from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import AuditLog, Membership, Organization


ROLE_PERMISSIONS = {
    Membership.Role.OWNER: {"*"},
    Membership.Role.MANAGER: {
        "core.change_branding",
        "core.manage_members",
        "engineering.change_project_status",
        "engineering.change_task_status",
        "engineering.add_project",
        "engineering.add_supplier",
        "engineering.add_task",
        "engineering.add_evidence",
        "engineering.add_employee",
        "engineering.add_finance",
        "engineering.add_purchase",
        "office.add_client",
        "office.add_task",
        "office.change_task_status",
        "office.add_staff",
        "office.add_case",
        "office.change_case_status",
        "office.view_confidential_case",
        "office.mark_confidential_case",
        "office.add_document",
        "office.add_finance",
        "office.change_finance_status",
        "office.add_purchase",
        "office.change_purchase_status",
        "partners.manage_network",
        "partners.manage_partners",
        "partners.manage_campaigns",
        "partners.manage_opportunities",
        "partners.view_network",
        "agro.add_farm",
        "agro.add_field",
        "agro.add_staff",
        "agro.add_supplier",
        "agro.add_inventory",
        "agro.add_operation",
        "agro.change_operation_status",
        "agro.add_finance",
        "agro.add_purchase",
    },
    Membership.Role.OPERATOR: {
        "engineering.change_project_status",
        "engineering.change_task_status",
        "engineering.add_project",
        "engineering.add_supplier",
        "engineering.add_task",
        "engineering.add_evidence",
        "engineering.add_employee",
        "engineering.add_finance",
        "engineering.add_purchase",
        "office.add_client",
        "office.add_task",
        "office.change_task_status",
        "office.add_staff",
        "office.add_case",
        "office.change_case_status",
        "office.add_document",
        "office.add_finance",
        "office.change_finance_status",
        "office.add_purchase",
        "office.change_purchase_status",
        "partners.manage_opportunities",
        "partners.view_network",
        "agro.add_farm",
        "agro.add_field",
        "agro.add_staff",
        "agro.add_supplier",
        "agro.add_inventory",
        "agro.add_operation",
        "agro.change_operation_status",
        "agro.add_finance",
        "agro.add_purchase",
    },
    Membership.Role.VIEWER: set(),
}


def available_organizations(user):
    if not user.is_authenticated:
        return Organization.objects.none()
    if user.is_superuser:
        organizations = Organization.objects.all()
    else:
        organizations = Organization.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
            status=Organization.Status.ACTIVE,
        ).distinct()
    if settings.JUMBI_LEGAL_ONLY:
        organizations = organizations.filter(business_type=Organization.BusinessType.OFFICE)
    return organizations


def active_organization(request):
    organizations = available_organizations(request.user)
    selected_id = request.session.get("active_organization_id")
    organization = organizations.filter(pk=selected_id).first() if selected_id else None
    return organization or organizations.first()


def require_active_organization(request):
    organization = active_organization(request)
    if organization is None:
        raise PermissionDenied("Sua conta ainda nao pertence a uma organizacao.")
    return organization


def require_business_organization(request, business_type):
    organizations = available_organizations(request.user)
    organization = active_organization(request)
    if organization is None or organization.business_type != business_type:
        organization = organizations.filter(business_type=business_type).first()
        if organization is None:
            raise PermissionDenied("Sua conta não possui acesso contratado para este sistema.")
        request.session["active_organization_id"] = organization.pk
    return organization


def active_membership(request):
    if not request.user.is_authenticated:
        return None
    organization = active_organization(request)
    if organization is None:
        return None
    return Membership.objects.filter(user=request.user, organization=organization, is_active=True).first()


def require_membership(request):
    membership = active_membership(request)
    if membership is None and not request.user.is_superuser:
        raise PermissionDenied("Sua conta nao tem acesso ativo a esta organizacao.")
    return membership


def require_permission(user, permission, organization):
    if not user.is_authenticated:
        raise PermissionDenied("Autenticacao obrigatoria.")
    if has_permission(user, permission, organization):
        return True
    membership = Membership.objects.filter(user=user, organization=organization, is_active=True).first()
    if membership is None:
        raise PermissionDenied("Sua conta nao tem acesso ativo a esta organizacao.")
    raise PermissionDenied("Sua conta nao tem permissao para executar esta acao.")


def has_permission(user, permission, organization):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    membership = Membership.objects.filter(user=user, organization=organization, is_active=True).first()
    if membership is None:
        return False
    permissions = ROLE_PERMISSIONS.get(membership.role, set())
    return "*" in permissions or permission in permissions


@transaction.atomic
def transition(*, instance, target_status, actor, permission, transition_map):
    require_permission(actor, permission, instance.organization)
    allowed = transition_map.get(instance.status, set())
    if target_status not in allowed:
        raise ValidationError("Transicao de estado invalida.")
    old_status = instance.status
    instance.status = target_status
    update_fields = ["status"]
    if any(field.name == "updated_at" for field in instance._meta.fields):
        update_fields.append("updated_at")
    instance.save(update_fields=update_fields)
    AuditLog.objects.create(
        organization=instance.organization,
        actor=actor,
        action=f"{instance._meta.label_lower}.status_changed",
        metadata={"before": old_status, "after": target_status, "id": str(instance.pk)},
    )
    return instance


AVAILABLE_MODULE_PERMISSIONS = [
    ("matters", "Pastas jurídicas"),
    ("contacts", "Pessoas e Clientes"),
    ("cases", "Processos"),
    ("tasks", "Tarefas e Kanban"),
    ("deadlines", "Prazos"),
    ("appointments", "Agenda e Calendário"),
    ("documents", "Documentos"),
    ("finance", "Financeiro"),
    ("fees", "Honorários"),
    ("crm", "Relacionamento e CRM"),
    ("marketing", "Marketing & Captação"),
    ("demands", "Previdenciário e INSS"),
    ("trabalhista", "Trabalhista e Audiências"),
    ("contracts", "Montar Contratos"),
    ("djen", "Comunica PJe / DJEN"),
    ("contadoria_prazos", "Contadoria Judicial & Prazos CPC"),
    ("pecas_minutas", "Banco de Peças & Assinatura SHA-256"),
    ("correicao_ia", "Correição Interna, CNJ & Triagem IA"),
    ("goals", "Metas"),
    ("ranking", "Ranking da Equipe"),
    ("tutorials", "Tutoriais e Treinamentos"),
    ("client_map", "Mapa de Clientes"),
    ("contact_messages", "Contatos e WhatsApp"),
    ("portal", "Revisão e Portal"),
    ("inventory", "Estoque e Patrimônio"),
    ("team", "Gestão da Equipe"),
    ("intake", "Importação de Planilhas"),
    ("audit", "Auditoria"),
    ("connectors", "Conectores e APIs"),
    ("customization", "Personalização & Visual"),
]


def member_has_module(membership, module_key):
    """Check if a membership has access to a specific module."""
    if membership is None:
        return False
    if membership.role == "owner":
        return True
    perms = getattr(membership, "permissions", None) or []
    # If no custom permissions assigned, fall back to default role permissions
    if not perms or "*" in perms:
        if membership.role == "client":
            return module_key in {"portal", "security"}
        if module_key in {"finance", "fees", "inventory"} and membership.role not in {"owner", "manager"}:
            return False
        if module_key in {"team", "customization", "audit", "connectors"} and membership.role not in {"owner", "manager"}:
            return False
        return True
    # If custom permissions are set, check explicit list
    # Always allow basic essentials
    if module_key in {"dashboard", "my_routine", "security", "guide"}:
        return True
    if module_key == "contadoria_prazos" and "deadlines" in perms:
        return True
    if module_key == "pecas_minutas" and "documents" in perms:
        return True
    if module_key == "correicao_ia" and "cases" in perms:
        return True
    return module_key in perms

