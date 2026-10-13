"""A compact, accessible contact workspace backed only by authorized records."""
from collections import Counter
from urllib.parse import urlencode

from django import forms
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import Lower
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.niches import practice_area_choices
from .calendar_services import normalize_whatsapp_phone
from .client_map_views import BRAZIL_STATES, REGION_CATEGORIES, STATE_NAMES, contact_region, normalized_text
from .models import Contact, CourtCase, Matter
from .niches import filter_niche
from .services import visible_matters
from .views import can_edit, organization_required, scoped_queryset


AGE_BANDS = (
    ("under18", "Até 17 anos", 18), ("18_29", "18–29 anos", 30),
    ("30_44", "30–44 anos", 45), ("45_59", "45–59 anos", 60),
    ("60plus", "60 anos ou mais", None), ("unknown", "Sem nascimento válido", None),
)


class DirectoryFilters(forms.Form):
    q = forms.CharField(label="Buscar pessoas", required=False, max_length=160,
                        widget=forms.TextInput(attrs={"placeholder": "Nome, CPF/CNPJ, telefone, e-mail ou cidade", "type": "search"}))
    kind = forms.ChoiceField(label="Tipo de pessoa", required=False, choices=[("", "Pessoas e empresas"), *Contact.Kind.choices])
    status = forms.ChoiceField(label="Situação do relacionamento", required=False, choices=[("", "Todas as situações"), *Contact.Status.choices])
    case = forms.ChoiceField(label="Vínculo com processo", required=False, choices=[("", "Todos os cadastros"), ("with", "Com processo em pasta em andamento"), ("without", "Sem processo em pasta em andamento")])
    state = forms.ChoiceField(label="Estado ou situação do endereço", required=False, choices=[("", "Todos os estados e países"), *BRAZIL_STATES, *REGION_CATEGORIES])
    niche = forms.ChoiceField(label="Nicho da pasta", required=False)
    sort = forms.ChoiceField(label="Ordenar", required=False, choices=[("name", "Nome · A a Z"), ("newest", "Cadastros mais recentes")])
    per_page = forms.TypedChoiceField(label="Por página", required=False, choices=[("25", "25 cadastros"), ("50", "50 cadastros")], coerce=int, empty_value=25)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["niche"].choices = [("", "Todos os nichos"), *practice_area_choices(organization)]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_sort(self):
        return self.cleaned_data.get("sort") or "name"

    def clean_q(self):
        value = self.cleaned_data.get("q", "").strip()
        if len(value.split()) > 8:
            raise forms.ValidationError("Use até oito palavras para pesquisar.")
        return value


def age_band(birth_date, today):
    if not birth_date or birth_date > today:
        return "unknown"
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    return next(key for key, _, upper in AGE_BANDS if upper is None or age < upper)


def demographics(queryset, today):
    """Charts refer to all filtered people, never just the current result page."""
    professions, labels, ages = Counter(), {}, Counter()
    people = 0
    for profession, birth_date in queryset.filter(kind=Contact.Kind.PERSON).values_list("profession", "birth_date").iterator(chunk_size=500):
        people += 1
        label = " ".join(profession.split())
        key = normalized_text(label) if label else ""
        professions[key] += 1
        if key and key not in labels:
            labels[key] = label[:1].upper() + label[1:]
        ages[age_band(birth_date, today)] += 1
    known = sorted(((key, count) for key, count in professions.items() if key), key=lambda item: (-item[1], item[0]))
    profession_rows = [{"label": labels[key], "count": count, "key": key} for key, count in known[:5]]
    remainder = sum(count for _, count in known[5:])
    if remainder:
        profession_rows.append({"label": "Outras profissões", "count": remainder, "key": "other"})
    profession_rows.append({"label": "Profissão não informada", "count": professions[""], "key": "unknown"})
    max_profession = max((item["count"] for item in profession_rows), default=0)
    for row in profession_rows:
        row["share"] = round(row["count"] * 100 / people, 1) if people else 0
        row["bar"] = round(row["count"] * 100 / max_profession, 2) if max_profession else 0
    age_rows, gradient, previous = [], [], 0
    for index, (key, label, _) in enumerate(AGE_BANDS):
        count = ages[key]
        share = count * 100 / people if people else 0
        age_rows.append({"key": key, "label": label, "count": count, "share": round(share, 1), "index": index})
        gradient.append(f"var(--directory-age-{index}) {previous:.4f}% {previous + share:.4f}%")
        previous += share
    return {"profession_rows": profession_rows, "age_rows": age_rows, "people_count": people,
            "age_gradient": ", ".join(gradient) if people else "var(--border-soft) 0% 100%",
            "profession_known": people - professions[""], "birth_known": people - ages["unknown"]}


def directory_context(request, criteria, *, valid=True):
    root = reverse("legal:list", args=["contacts"])
    records = scoped_queryset(request.user, request.organization, Contact) if valid else Contact.objects.none()
    matters = visible_matters(request.user, request.organization)
    if criteria["niche"]:
        matters = filter_niche(matters, criteria["niche"], practice_area_choices(request.organization))
        records = records.filter(pk__in=matters.values("client_id"))
    for field in ("kind", "status"):
        if criteria[field]:
            records = records.filter(**{field: criteria[field]})
    for term in criteria["q"].split():
        records = records.filter(Q(name__icontains=term) | Q(trade_name__icontains=term) | Q(document__icontains=term)
                                 | Q(email__icontains=term) | Q(phone__icontains=term) | Q(city__icontains=term))
    if criteria["state"]:
        ids = [pk for pk, state, country in records.values_list("pk", "state", "country").iterator(chunk_size=500)
               if contact_region(state, country) == criteria["state"]]
        records = records.filter(pk__in=ids)
    cases = CourtCase.objects.filter(organization=request.organization, matter__in=matters.filter(status=Matter.Status.ACTIVE), matter__client_id=OuterRef("pk"))
    records = records.annotate(has_current_case=Exists(cases))
    counts = records.aggregate(total=Count("pk"), with_case=Count("pk", filter=Q(has_current_case=True)))
    counts["without_case"] = counts["total"] - counts["with_case"]
    if criteria["case"]:
        records = records.filter(has_current_case=criteria["case"] == "with")
    chart = demographics(records, timezone.localdate())
    order = [Lower("name"), "pk"] if criteria["sort"] == "name" else ["-created_at", "-pk"]
    page = Paginator(records.defer("notes", "representatives").order_by(*order), criteria["per_page"]).get_page(request.GET.get("page"))
    base = {key: value for key, value in criteria.items() if value}

    def select_case(value):
        query = {key: val for key, val in base.items() if key != "case"}
        if value:
            query["case"] = value
        return root + "?" + urlencode(query) + "#directory-results"

    rows = []
    category_names = dict(REGION_CATEGORIES)
    for record in page:
        region = contact_region(record.state, record.country)
        state = STATE_NAMES.get(region, category_names.get(region, ""))
        phone = normalize_whatsapp_phone(record.phone)
        rows.append({"record": record, "state_code": region if region in STATE_NAMES else "",
                     "state_label": state, "region": region,
                     "detail_url": reverse("legal:contact_detail", args=[record.pk]),
                     "edit_url": reverse("legal:edit", args=["contacts", record.pk]),
                     "whatsapp_url": "https://wa.me/" + phone + "?" + urlencode({"text": f"Olá, {record.name}! Estamos entrando em contato pelo {request.organization.name}."}) if phone else ""})
    return {
        "page_title": "Pessoas", "title": "Pessoas", "active_nav": "contacts", "module": "contacts",
        "module_template": "legal/contact_directory.html", "can_create": can_edit(request),
        "create_url": reverse("legal:create", args=["contacts"]), "rows": rows, "page_obj": page,
        "criteria": criteria, "filtered_count": page.paginator.count, "counts": counts, "filter_valid": valid,
        "has_filters": any(criteria[key] for key in ("q", "kind", "status", "case", "state", "niche")),
        "advanced_filters": any(criteria[key] for key in ("kind", "status", "case", "state", "niche")),
        "pagination_query": urlencode(base), "clear_url": root,
        "directory_cards": [
            {"key": "all", "label": "Todos os cadastros", "value": counts["total"], "detail": "Pessoas e empresas", "url": select_case(""), "selected": not criteria["case"], "icon": "contacts"},
            {"key": "with", "label": "Com processo em pasta em andamento", "value": counts["with_case"], "detail": "Somente pastas que você pode acessar", "url": select_case("with"), "selected": criteria["case"] == "with", "icon": "cases"},
            {"key": "without", "label": "Sem processo em pasta em andamento", "value": counts["without_case"], "detail": "Inclui cadastros sem demanda judicial", "url": select_case("without"), "selected": criteria["case"] == "without", "icon": "contacts"},
        ], **chart,
    }


@organization_required
@require_GET
def directory(request):
    data = request.GET.copy()
    # Preserve old bookmarks whose status parameter represented PF/PJ.
    if data.get("status") in Contact.Kind.values and not data.get("kind"):
        data["kind"], data["status"] = data["status"], ""
    form = DirectoryFilters(data, organization=request.organization)
    valid = form.is_valid()
    criteria = form.cleaned_data if valid else {"q": "", "kind": "", "status": "", "case": "", "state": "", "niche": "", "sort": "name", "per_page": 25}
    context = directory_context(request, criteria, valid=valid)
    context["filter_form"] = form
    response = render(request, "legal/contact_directory.html", context, status=200 if valid else 400)
    response["Cache-Control"] = "private, no-store"
    return response
