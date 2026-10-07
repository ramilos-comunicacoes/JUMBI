from django.urls import reverse

from .models import Organization


SEGMENT_APPS = {
    "office": {
        "key": "juridico",
        "label": "Jumbi Jurídico",
        "short_label": "Jurídico",
        "description": "Gestão completa para escritórios jurídicos.",
        "business_type": Organization.BusinessType.OFFICE,
        "namespace": "office",
        "icon": "scale",
        "sections": (
            ("overview", "Visão geral", "layout-dashboard"),
            ("clients", "Clientes", "users"),
            ("cases", "Processos e casos", "briefcase-business"),
            ("practice", "Áreas e fluxos", "workflow"),
            ("tasks", "Agenda e prazos", "calendar-clock"),
            ("documents", "Documentos", "files"),
            ("finance", "Financeiro", "circle-dollar-sign"),
            ("staff", "Equipe", "users-round"),
            ("partners", "Rede de parceiros", "handshake"),
            ("purchases", "Compras", "shopping-bag"),
            ("accesses", "Hierarquia e acessos", "network"),
            ("settings", "Personalização", "palette"),
        ),
    },
    "engineering": {
        "key": "engenharia",
        "label": "Djumbi Engenharia",
        "short_label": "Engenharia",
        "description": "Gestão operacional para escritórios, construtoras e obras.",
        "business_type": Organization.BusinessType.ENGINEERING,
        "namespace": "engineering",
        "icon": "hard-hat",
        "sections": (
            ("overview", "Visão geral", "layout-dashboard"),
            ("projects", "Obras", "building-2"),
            ("tasks", "Tarefas e Kanban", "kanban-square"),
            ("suppliers", "Fornecedores", "truck"),
            ("purchases", "Compras", "shopping-cart"),
            ("finance", "Financeiro", "circle-dollar-sign"),
            ("staff", "Equipe técnica", "users-round"),
            ("evidences", "Evidências", "file-check-2"),
            ("accesses", "Hierarquia e acessos", "network"),
            ("settings", "Personalização", "palette"),
        ),
    },
    "agro": {
        "key": "agro",
        "label": "Djumbi Agro",
        "short_label": "Agro",
        "description": "Gestão de fazendas, produção e operação rural.",
        "business_type": Organization.BusinessType.AGRO,
        "namespace": "agro",
        "icon": "sprout",
        "sections": (
            ("overview", "Visão geral", "layout-dashboard"),
            ("farms", "Fazendas", "warehouse"),
            ("fields", "Talhões e safras", "grid-3x3"),
            ("operations", "Operações", "tractor"),
            ("inventory", "Estoque e insumos", "package-search"),
            ("purchases", "Compras", "shopping-cart"),
            ("finance", "Financeiro", "circle-dollar-sign"),
            ("suppliers", "Fornecedores", "truck"),
            ("staff", "Equipe rural", "users-round"),
            ("accesses", "Hierarquia e acessos", "network"),
            ("settings", "Personalização", "palette"),
        ),
    },
}

CONTROL_APP = {
    "key": "control",
    "label": "Controle Jumbi",
    "short_label": "Superusuário",
    "icon": "shield-cog",
    "sections": (
        ("overview", "Visão geral", "layout-dashboard"),
        ("organizations", "Organizações", "building-2"),
        ("accesses", "Usuários e acessos", "key-round"),
        ("audit", "Auditoria", "scroll-text"),
    ),
}


def app_shell_context(app_name, section):
    app = SEGMENT_APPS[app_name]
    sections = app["sections"]
    valid_sections = {item[0] for item in sections}
    if section not in valid_sections:
        return None
    namespace = app["namespace"]
    items = []
    for key, label, icon in sections:
        url = reverse(f"{namespace}:workspace") if key == "overview" else reverse(
            f"{namespace}:section", kwargs={"section": key}
        )
        items.append({"key": key, "label": label, "icon": icon, "url": url})
    return {
        "app_key": app["key"],
        "app_label": app["label"],
        "app_short_label": app["short_label"],
        "app_icon": app["icon"],
        "app_home_url": reverse(f"{namespace}:workspace"),
        "sidebar_items": items,
        "current_section": section,
        "current_section_label": next(item["label"] for item in items if item["key"] == section),
    }


def control_shell_context(section):
    sections = CONTROL_APP["sections"]
    valid_sections = {item[0] for item in sections}
    if section not in valid_sections:
        return None
    items = []
    for key, label, icon in sections:
        url = reverse("core:control-panel") if key == "overview" else reverse(
            "core:control-section", kwargs={"section": key}
        )
        items.append({"key": key, "label": label, "icon": icon, "url": url})
    return {
        "app_key": CONTROL_APP["key"],
        "app_label": CONTROL_APP["label"],
        "app_short_label": CONTROL_APP["short_label"],
        "app_icon": CONTROL_APP["icon"],
        "app_home_url": reverse("core:control-panel"),
        "sidebar_items": items,
        "current_section": section,
        "current_section_label": next(item["label"] for item in items if item["key"] == section),
    }
