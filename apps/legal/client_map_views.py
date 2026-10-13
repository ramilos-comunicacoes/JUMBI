"""Country-level client distribution from explicit contact fields, without geocoding."""
import unicodedata
from math import ceil
from urllib.parse import urlencode

from django import forms
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .models import Contact
from .services import visible_matters
from .views import can_edit, organization_required, scoped_queryset


BRAZIL_STATES = (
    ("AC", "Acre"), ("AL", "Alagoas"), ("AP", "Amapá"), ("AM", "Amazonas"),
    ("BA", "Bahia"), ("CE", "Ceará"), ("DF", "Distrito Federal"), ("ES", "Espírito Santo"),
    ("GO", "Goiás"), ("MA", "Maranhão"), ("MT", "Mato Grosso"), ("MS", "Mato Grosso do Sul"),
    ("MG", "Minas Gerais"), ("PA", "Pará"), ("PB", "Paraíba"), ("PR", "Paraná"),
    ("PE", "Pernambuco"), ("PI", "Piauí"), ("RJ", "Rio de Janeiro"),
    ("RN", "Rio Grande do Norte"), ("RS", "Rio Grande do Sul"), ("RO", "Rondônia"),
    ("RR", "Roraima"), ("SC", "Santa Catarina"), ("SP", "São Paulo"),
    ("SE", "Sergipe"), ("TO", "Tocantins"),
)
STATE_NAMES = dict(BRAZIL_STATES)
REGION_CATEGORIES = (
    ("missing", "Estado não informado"),
    ("unknown", "Estado não reconhecido"),
    ("outside", "Fora do Brasil"),
)


def normalized_text(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    return " ".join("".join(character for character in normalized if not unicodedata.combining(character)).casefold().split())


STATE_ALIASES = {normalized_text(value): code for code, name in BRAZIL_STATES for value in (code, name)}
BRAZIL_ALIASES = {"", "brasil", "brazil", "br", "bra", "republica federativa do brasil"}


def contact_region(state, country):
    """Only the entered state and country count; never infer location from CEP/city."""
    if normalized_text(country) not in BRAZIL_ALIASES:
        return "outside"
    state = normalized_text(state)
    return STATE_ALIASES.get(state, "unknown" if state else "missing")


class MapFilterForm(forms.Form):
    state = forms.ChoiceField(label="Estado ou situação", required=False, choices=[("", "Brasil inteiro"), *BRAZIL_STATES, *REGION_CATEGORIES])
    scope = forms.ChoiceField(label="Cadastros considerados", required=False, initial="all", choices=[("all", "Todos os cadastros"), ("with_matter", "Clientes com pasta acessível")])
    kind = forms.ChoiceField(label="Tipo de pessoa", required=False, choices=[("", "Pessoas e empresas"), *Contact.Kind.choices])
    q = forms.CharField(label="Buscar nome ou cidade", required=False, max_length=120, widget=forms.TextInput(attrs={"placeholder": "Nome, nome fantasia ou cidade"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_scope(self):
        return self.cleaned_data.get("scope") or "all"

    def clean_q(self):
        value = self.cleaned_data.get("q", "").strip()
        if len(value.split()) > 8:
            raise forms.ValidationError("Use até oito palavras na busca.")
        return value


def map_context(request, filters):
    records = scoped_queryset(request.user, request.organization, Contact)
    if filters["scope"] == "with_matter":
        records = records.filter(pk__in=visible_matters(request.user, request.organization).values("client_id"))
    if filters["kind"]:
        records = records.filter(kind=filters["kind"])
    for term in filters["q"].split():
        records = records.filter(Q(name__icontains=term) | Q(trade_name__icontains=term) | Q(city__icontains=term))

    # Load only regional metadata for aggregation. Personal profile details are
    # fetched for a single page below, and never sent to a mapping provider.
    counts = {code: 0 for code, _ in BRAZIL_STATES}
    counts.update({key: 0 for key, _ in REGION_CATEGORIES})
    selected_ids = []
    for pk, state, country in records.values_list("pk", "state", "country").iterator(chunk_size=500):
        region = contact_region(state, country)
        counts[region] += 1
        if filters["state"] and filters["state"] == region:
            selected_ids.append(pk)
    if filters["state"]:
        records = records.filter(pk__in=selected_ids)
    return _present_context(request, filters, records, counts)


def _present_context(request, filters, records, counts):
    root = reverse("legal:client_map")
    base = {key: value for key, value in filters.items() if value and key != "state"}

    def region_url(state):
        return root + "?" + urlencode({**base, "state": state}) + "#client-map-results"

    mapped = sum(counts[code] for code, _ in BRAZIL_STATES)
    totals = {
        "clients": sum(counts.values()), "mapped": mapped,
        "missing": counts["missing"], "unknown": counts["unknown"], "outside": counts["outside"],
        "states": sum(counts[code] > 0 for code, _ in BRAZIL_STATES),
    }
    max_count = max((counts[code] for code, _ in BRAZIL_STATES), default=0)
    state_rows = [{
        "uf": code, "name": name, "count": counts[code], "selected": filters["state"] == code,
        "url": region_url(code), "share": round(counts[code] * 100 / mapped, 1) if mapped else 0,
        "level": ceil(counts[code] * 4 / max_count) if max_count else 0,
    } for code, name in BRAZIL_STATES]
    page = Paginator(records.order_by("name", "pk"), 12).get_page(request.GET.get("page"))
    category_names = dict(REGION_CATEGORIES)
    for contact in page:
        region = contact_region(contact.state, contact.country)
        contact.map_region = region
        contact.map_state_code = region if region in STATE_NAMES else ""
        contact.map_state_label = STATE_NAMES.get(region, category_names.get(region))
    return {
        "page_title": "Mapa de clientes", "active_nav": "client_map", "can_edit": can_edit(request),
        "state_rows": state_rows, "state_counts": {row["uf"]: row["count"] for row in state_rows},
        "ranking_rows": sorted((row for row in state_rows if row["count"]), key=lambda row: (-row["count"], row["name"])),
        "max_state_count": max_count,
        "totals": totals, "selected_state": filters["state"], "selected_kind": filters["kind"],
        "selected_scope": filters["scope"], "query": filters["q"],
        "selected_label": STATE_NAMES.get(filters["state"], category_names.get(filters["state"], "Todos os cadastros selecionados")),
        "category_rows": [{"key": key, "label": label, "count": counts[key], "url": region_url(key), "selected": filters["state"] == key} for key, label in REGION_CATEGORIES],
        "clear_state_url": root + ("?" + urlencode(base) if base else ""),
        "pagination_query": urlencode({key: value for key, value in filters.items() if value}),
        "client_page": page, "filtered_count": page.paginator.count,
    }


@organization_required
@require_GET
def client_map(request):
    form = MapFilterForm(request.GET)
    valid = form.is_valid()
    if valid:
        context = map_context(request, form.cleaned_data)
    else:
        # A malformed filter must not silently widen the requested scope.
        filters = {"state": "", "scope": "all", "kind": "", "q": ""}
        counts = {code: 0 for code, _ in (*BRAZIL_STATES, *REGION_CATEGORIES)}
        context = _present_context(request, filters, Contact.objects.none(), counts)
    context["filter_form"] = form
    response = render(request, "legal/client_map.html", context, status=200 if valid else 400)
    response["Cache-Control"] = "private, no-store"
    return response
