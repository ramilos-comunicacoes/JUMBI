from django.urls import reverse
from django.utils import timezone


def workspace_context(request):
    organization = getattr(request, "organization", None)
    membership = getattr(request, "membership", None)
    from .preferences import office_preferences, brand_tokens
    prefs = office_preferences(organization)
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
    practice_areas = getattr(organization, "practice_areas", []) or []
    is_prev = "previdenciario" in practice_areas or not practice_areas
    is_trab = "trabalhista" in practice_areas or not practice_areas

    nav = [
        {"key": "dashboard", "label": "Visão geral", "url": reverse("legal:dashboard"), "icon": "grid"},
        {"key": "my_routine", "label": "Minha rotina", "url": reverse("legal:my_routine"), "icon": "my_routine"},
        {"key": "djen", "label": "Comunica PJe / DJEN", "url": reverse("legal:djen_dashboard"), "icon": "djen"},
    ]
    if is_prev:
        nav.append({"key": "demands", "label": "Previdenciário & INSS", "url": reverse("legal:previdenciario_hub"), "icon": "demands"})
    if is_trab:
        nav.append({"key": "trabalhista", "label": "Trabalhista & Audiências", "url": reverse("legal:trabalhista_hub"), "icon": "scale"})

    nav.extend({"key": key, "label": label, "icon": icon, "url": reverse("legal:list", args=[key])}
               for key, label, icon in sections if key != "demands")

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
            {"key": "team", "label": "Equipe", "url": reverse("core:team"), "icon": "users"},
            {"key": "intake", "label": "Importar planilha", "url": reverse("intake:home"), "icon": "intake"},
            {"key": "audit", "label": "Auditoria", "url": reverse("core:audit"), "icon": "shield"},
            {"key": "connectors", "label": "Conectores e APIs", "url": reverse("integrations:connectors"), "icon": "connectors"},
            {"key": "customization", "label": "Personalização & Visual", "url": reverse("core:customization"), "icon": "customization"},
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
        ("Dia a dia", ["my_routine", "dashboard", "tasks", "deadlines", "appointments", "djen"]),
        ("Módulos Especializados", ["demands", "trabalhista"]),
        ("Acervo jurídico", ["matters", "contacts", "cases", "documents", "contact_messages", "client_map", "contracts", "portal"]),
        ("Gestão do escritório", ["ranking", "goals", "crm", "fees", "finance", "inventory", "tutorials"]),
        ("Administração", ["team", "intake", "audit", "subscription", "guide", "security", "connectors", "customization", "platform"]),
    ]

    indexed_nav = {item["key"]: item for item in nav}
    nav = [dict(indexed_nav[key], group=group) for group, keys in navigation_groups
           for key in keys if key in indexed_nav]
    from apps.core.services import member_has_module
    nav = [item for item in nav if item["key"] not in prefs["hidden_nav"] and (manager or item["key"] != "djen") and member_has_module(membership, item["key"])]
    if prefs["nav_order"]:
        priorities = {key: pos for pos, key in enumerate(prefs["nav_order"])}
        nav.sort(key=lambda item: priorities.get(item["key"], len(priorities)))
        nav = [dict(item, group="Meu escritório" if item["key"] in priorities else item["group"]) for item in nav]
    notification_count = 0
    if organization and membership and membership.role != 'client' and subscription and subscription.is_available:
        from apps.notifications.services import unread_count
        notification_count = unread_count(request)
    can_reset = bool(membership and (membership.role == 'owner' or getattr(request.user, 'is_superuser', False)))
    return {
        "organization": organization, "membership": membership, "nav": nav,
        "office_preferences": prefs, "brand_tokens": brand_tokens(organization),
        "preference_key": f"jumbi:{getattr(organization, 'pk', 0)}:{getattr(request.user, 'pk', 0)}",
        "plan_catalog": PLANS,
        "can_edit": bool(membership and membership.role in {'owner', 'manager', 'operator'}),
        "can_manage": manager, "can_reset": can_reset, "today": timezone.localdate(),
        "notification_count": notification_count,
        "is_demo": bool((subscription and subscription.status == "demo") or (organization and organization.slug in {"jumbi-demonstracao-local", "jumbi-demonstracao"})),
        "workspace_memberships": request.user.memberships.filter(is_active=True, organization__status="active", organization__business_type="office").select_related("organization") if request.user.is_authenticated else [],
    }
