"""Versioned, allowlisted office preferences; never authorization rules."""
from copy import deepcopy
import re

from django.core.exceptions import ValidationError

NAV_CHOICES = [
    ("my_routine", "Minha rotina"), ("dashboard", "Visão geral"),
    ("tasks", "Tarefas · Kanban"), ("deadlines", "Prazos"), ("appointments", "Calendário"),
    ("djen", "DJEN"), ("demands", "Previdenciário"), ("trabalhista", "Trabalhista"),
    ("matters", "Pastas"), ("contacts", "Pessoas"), ("cases", "Processos"),
    ("documents", "Documentos"), ("contact_messages", "Mensagens"), ("client_map", "Mapa"),
    ("contracts", "Contratos"), ("portal", "Portal"), ("ranking", "Ranking"),
    ("goals", "Metas"), ("crm", "Relacionamento"), ("fees", "Honorários"),
    ("finance", "Financeiro"), ("inventory", "Estoque"), ("tutorials", "Tutoriais e rotinas"),
]
WIDGET_CHOICES = [("calendar", "Calendário e aniversários"), ("goals", "Metas"),
    ("insights", "Gráficos e financeiro"), ("activity", "Pastas e atividade recente"),
    ("routines", "Conferências de rotinas"), ("crm", "Relacionamento"), ("inventory", "Estoque")]
CHOICES = {
    "theme": [("dark", "Escuro"), ("light", "Claro"), ("system", "Seguir dispositivo")],
    "density": [("comfortable", "Confortável"), ("compact", "Compacta no desktop")],
    "text_size": [("normal", "Padrão"), ("large", "Ampliado")],
    "sidebar_mode": [("auto", "Abrir ao passar o mouse"), ("manual", "Controle pelo botão")],
    "motion": [("auto", "Animações suaves"), ("paused", "Reduzir movimentos")],
    "calendar_view": [("month", "Mês"), ("week", "Semana"), ("day", "Dia")],
    "dashboard_view": [("office", "Completo"), ("compact", "Resumo operacional")],
    "landing_page": [("dashboard", "Visão geral"), ("my_routine", "Minha rotina"), ("kanban", "Kanban"), ("calendar", "Calendário")],
}
DEFAULTS = {"theme": "dark", "density": "comfortable", "text_size": "normal",
    "sidebar_mode": "auto", "motion": "auto", "calendar_view": "month",
    "dashboard_view": "office", "landing_page": "dashboard",
    "hidden_nav": [], "nav_order": [], "dashboard_widgets": [key for key, _ in WIDGET_CHOICES],
    "djen_name": "", "birthday_message": "Olá, {cliente}! A equipe {escritorio} deseja um feliz aniversário, com muita saúde e realizações!"}


def validate_preferences(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValidationError("Preferências inválidas.")
    for name, options in CHOICES.items():
        if name in value and value[name] not in dict(options):
            raise ValidationError(f"Opção inválida: {name}.")
    for name, options in [("hidden_nav", NAV_CHOICES), ("nav_order", NAV_CHOICES), ("dashboard_widgets", WIDGET_CHOICES)]:
        items = value.get(name, [])
        if not isinstance(items, list) or len(items) > len(options) or any(not isinstance(x, str) or x not in dict(options) for x in items) or len(set(items)) != len(items):
            raise ValidationError(f"Seleção inválida: {name}.")
    for name, limit in [("djen_name", 200), ("birthday_message", 1200)]:
        if name in value and (not isinstance(value[name], str) or len(value[name]) > limit):
            raise ValidationError(f"Texto inválido: {name}.")
    message = value.get("birthday_message", "")
    if any(x not in {"cliente", "escritorio"} for x in re.findall(r"\{([^{}]+)\}", message)):
        raise ValidationError("A mensagem aceita somente {cliente} e {escritorio}.")


def office_preferences(organization):
    defaults = deepcopy(DEFAULTS)
    value = getattr(organization, "workspace_preferences", {}) or {}
    try:
        validate_preferences(value)
    except (ValidationError, TypeError):
        return defaults
    defaults.update(value)
    return defaults


def safe_color(value, fallback):
    return value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


def contrasting_ink(value):
    channels = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
    channels = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in channels]
    luminance = sum(x * weight for x, weight in zip(channels, (.2126, .7152, .0722)))
    return "#10131a" if luminance > .179 else "#ffffff"


def brand_tokens(organization):
    primary = safe_color(getattr(organization, "brand_primary_color", ""), "#F5A000")
    sidebar = safe_color(getattr(organization, "brand_sidebar_color", ""), "#0B1320")
    return {"primary": primary, "primary_ink": contrasting_ink(primary), "sidebar": sidebar,
        "sidebar_ink": contrasting_ink(sidebar),
        "accent": safe_color(getattr(organization, "brand_accent_color", ""), "#0F4050")}
