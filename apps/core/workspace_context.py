from django.urls import reverse
from django.utils import timezone


def workspace_context(request):
    organization = getattr(request, "organization", None)
    membership = getattr(request, "membership", None)
    manager = bool(membership and membership.role in {"owner", "manager"})
    from apps.billing.services import has_advanced, subscription_for
    from apps.billing.plans import PLANS
    subscription = subscription_for(organization)
    advanced = has_advanced(organization)
    sections = [
        ("matters", "Pastas jurídicas", "folder"), ("contacts", "Pessoas", "users"),
        ("demands", "INSS / Previdenciário", "demands"),
        ("cases", "Processos", "scale"), ("tasks", "Tarefas", "check"),
        ("deadlines", "Prazos", "clock"), ("appointments", "Agenda", "calendar"),
        ("documents", "Documentos", "file"),
    ]
    if manager and advanced:
        sections.append(("finance", "Financeiro", "wallet"))
    sections.append(("crm", "Relacionamento", "briefcase"))
    nav = [{"key": "dashboard", "label": "Visão geral", "url": reverse("legal:dashboard"), "icon": "grid"}]
    nav.append({"key": "my_routine", "label": "Minha rotina", "url": reverse("legal:my_routine"), "icon": "my_routine"})
    nav.append({"key": "djen", "label": "Comunica PJe / DJEN", "url": reverse("legal:djen_dashboard"), "icon": "djen"})
    nav.extend([
        {"key": "search", "label": "Busca unificada", "url": reverse("discovery:search"), "icon": "search"},
        {"key": "notifications", "label": "Notificações", "url": reverse("notifications:inbox"), "icon": "notifications"},
    ])
    nav.extend({"key": key, "label": label, "icon": icon, "url": reverse("legal:list", args=[key])}
               for key, label, icon in sections)
    for item in nav:
        if item["key"] == "tasks":
            item.update(label="Tarefas · Kanban", url=reverse("legal:kanban"))
        elif item["key"] == "appointments":
            item.update(label="Calendário e agenda", url=reverse("legal:calendar"))
    nav.append({"key": "goals", "label": "Metas", "url": reverse("performance:list"), "icon": "target"})
    nav.append({"key": "ranking", "label": "Ranking da equipe", "url": reverse("performance:ranking"), "icon": "ranking"})
    nav.append({"key": "contact_messages", "label": "Contatos e WhatsApp", "url": reverse("legal:contact_messages_list"), "icon": "contact_messages"})
    nav.append({"key": "tutorials", "label": "Tutoriais e Treinamentos", "url": reverse("routines:list"), "icon": "tutorials"})
    if manager and advanced:
        nav.append({"key": "fees", "label": "Honorários", "url": reverse("fees:overview"), "icon": "wallet"})
        nav.append({"key": "inventory", "label": "Estoque e patrimônio", "url": reverse("inventory:overview"), "icon": "box"})
    if membership and membership.role in {'owner', 'manager', 'operator'}:
        nav.append({"key": "portal", "label": "Revisão e portal", "url": reverse("portal:manage"), "icon": "file"})
    if advanced:
        nav.append({"key": "contracts", "label": "Montar contratos", "url": reverse("contracts:library"), "icon": "file"})
    nav.append({"key": "security", "label": "Segurança da conta", "url": reverse("security:account"), "icon": "shield"})
    nav.append({"key": "client_map", "label": "Mapa de clientes", "url": reverse("legal:client_map"), "icon": "map"})
    nav.append({"key": "guide", "label": "Como usar o JUMBI", "url": reverse("legal:guide"), "icon": "help"})
    if manager:
        nav.extend([
            {"key": "intake", "label": "Importar planilha", "url": reverse("intake:home"), "icon": "intake"},
            {"key": "team", "label": "Equipe", "url": reverse("core:team"), "icon": "users"},
            {"key": "audit", "label": "Auditoria", "url": reverse("core:audit"), "icon": "shield"},
        ])
    if organization:
        nav.append({"key": "subscription", "label": "Plano e assinatura", "url": reverse("billing:subscription"), "icon": "wallet"})
    if request.user.is_authenticated and request.user.is_superuser:
        nav.append({"key": "platform", "label": "Administração JUMBI", "url": reverse("core:platform"), "icon": "shield"})
    if membership and membership.role == 'client':
        nav = [
            {'key': 'portal', 'label': 'Meus documentos', 'url': reverse('portal:home'), 'icon': 'file'},
            {'key': 'security', 'label': 'Segurança da conta', 'url': reverse('security:account'), 'icon': 'shield'},
        ]
    navigation_groups = [
        ("Dia a dia", ["my_routine", "dashboard", "demands", "djen", "ranking", "tutorials", "search", "notifications", "appointments", "tasks", "deadlines", "goals", "routines"]),
        ("Acervo jurídico", ["matters", "contacts", "contact_messages", "client_map", "cases", "documents", "portal", "contracts"]),
        ("Gestão do escritório", ["crm", "fees", "finance", "inventory"]),
        ("Administração", ["intake", "team", "audit", "subscription", "guide", "security", "platform"]),
    ]

    indexed_nav = {item["key"]: item for item in nav}
    nav = [dict(indexed_nav[key], group=group) for group, keys in navigation_groups
           for key in keys if key in indexed_nav]
    notification_count = 0
    if organization and membership and membership.role != 'client' and subscription and subscription.is_available:
        from apps.notifications.services import unread_count
        notification_count = unread_count(request)
    return {
        "organization": organization, "membership": membership, "nav": nav,
        "plan_catalog": PLANS,
        "can_edit": bool(membership and membership.role in {'owner', 'manager', 'operator'}),
        "can_manage": manager, "today": timezone.localdate(),
        "notification_count": notification_count,
        "is_demo": bool((subscription and subscription.status == "demo") or (organization and organization.slug in {"jumbi-demonstracao-local", "jumbi-demonstracao"})),
        "workspace_memberships": request.user.memberships.filter(is_active=True, organization__status="active", organization__business_type="office").select_related("organization") if request.user.is_authenticated else [],
    }
