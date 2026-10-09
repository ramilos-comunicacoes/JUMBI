from django.urls import reverse
from django.utils import timezone


def workspace_context(request):
    organization = getattr(request, "organization", None)
    membership = getattr(request, "membership", None)
    manager = bool(membership and membership.role in {"owner", "manager"})
    from apps.billing.services import has_advanced, subscription_for
    subscription = subscription_for(organization)
    advanced = has_advanced(organization)
    sections = [
        ("matters", "Pastas jurídicas", "folder"), ("contacts", "Pessoas", "users"),
        ("cases", "Processos", "scale"), ("tasks", "Tarefas", "check"),
        ("deadlines", "Prazos", "clock"), ("appointments", "Agenda", "calendar"),
        ("documents", "Documentos", "file"),
    ]
    if manager and advanced:
        sections.append(("finance", "Financeiro", "wallet"))
    if advanced:
        sections.append(("crm", "Relacionamento", "briefcase"))
    nav = [{"key": "dashboard", "label": "Visão geral", "url": reverse("legal:dashboard"), "icon": "grid"}]
    nav.extend({"key": key, "label": label, "icon": icon, "url": reverse("legal:list", args=[key])}
               for key, label, icon in sections)
    for item in nav:
        if item["key"] == "tasks":
            item.update(label="Tarefas · Kanban", url=reverse("legal:kanban"))
        elif item["key"] == "appointments":
            item.update(label="Calendário e agenda", url=reverse("legal:calendar"))
    nav.append({"key": "goals", "label": "Metas", "url": reverse("performance:list"), "icon": "target"})
    if advanced:
        nav.append({"key": "contracts", "label": "Montar contratos", "url": reverse("contracts:library"), "icon": "file"})
    if manager:
        nav.extend([
            {"key": "team", "label": "Equipe", "url": reverse("core:team"), "icon": "users"},
            {"key": "audit", "label": "Auditoria", "url": reverse("core:audit"), "icon": "shield"},
        ])
    if organization:
        nav.append({"key": "subscription", "label": "Plano e assinatura", "url": reverse("billing:subscription"), "icon": "wallet"})
    if request.user.is_authenticated and request.user.is_superuser:
        nav.append({"key": "platform", "label": "Administração JUMBI", "url": reverse("core:platform"), "icon": "shield"})
    birthday_count = 0
    if organization and membership and subscription and subscription.is_available:
        from apps.legal.calendar_services import birthday_context
        birthday_count = birthday_context(request)["birthday_today_count"]
    return {
        "organization": organization, "membership": membership, "nav": nav,
        "can_edit": bool(membership and membership.role != "viewer"),
        "can_manage": manager, "today": timezone.localdate(),
        "birthday_notification_count": birthday_count,
        "is_demo": bool((subscription and subscription.status == "demo") or (organization and organization.slug in {"jumbi-demonstracao-local", "jumbi-demonstracao"})),
        "workspace_memberships": request.user.memberships.filter(is_active=True, organization__status="active", organization__business_type="office").select_related("organization") if request.user.is_authenticated else [],
    }
