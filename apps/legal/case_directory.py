"""Read-only case directory. A case's situation always refers to its matter."""

from collections import defaultdict

from django import forms
from django.contrib.auth import get_user_model
from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, Q
from django.http import QueryDict
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from apps.core.models import Membership
from apps.core.niches import PRACTICE_AREA_LABELS, practice_area_choices
from .models import CourtCase, Matter
from .services import visible_matters


SORTS = {
    "newest": ("-created_at", "-pk"),
    "oldest": ("created_at", "pk"),
    "number": ("number", "pk"),
}
INTERNAL_ROLES = ("owner", "manager", "operator", "viewer")


def _user_label(user):
    return user.get_full_name().strip() or user.email


class DirectoryFilters(forms.Form):
    q = forms.CharField(
        label="Buscar processo", max_length=200, required=False,
        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Número, cliente, pasta, órgão ou contraparte", "autocomplete": "off"}),
    )
    status = forms.ChoiceField(label="Situação da pasta", required=False, choices=[("", "Todas as situações"), *Matter.Status.choices])
    niche = forms.ChoiceField(label="Nicho da pasta", required=False)
    owner = forms.ModelChoiceField(label="Responsável pela pasta", required=False, queryset=get_user_model().objects.none(), empty_label="Todos os responsáveis")
    sort = forms.ChoiceField(label="Ordenar por", choices=[("newest", "Cadastro mais recente"), ("oldest", "Cadastro mais antigo"), ("number", "Número do processo")])
    per_page = forms.TypedChoiceField(label="Por página", choices=[("25", "25 processos"), ("50", "50 processos")], coerce=int)
    page = forms.IntegerField(min_value=1, max_value=1000000, widget=forms.HiddenInput)

    def __init__(self, data, *, owners, niches):
        data = data.copy()
        # Defaults apply only to absent parameters. Malformed values, including
        # an explicit empty sort or page, never turn into a broader query.
        for name, default in (("sort", "newest"), ("per_page", "25"), ("page", "1")):
            if name not in data:
                data[name] = default
        super().__init__(data, auto_id="case-filter-%s")
        self.fields["owner"].queryset = owners
        self.fields["owner"].label_from_instance = _user_label
        self.fields["niche"].choices = [("", "Todos os nichos"), *niches]

    def clean(self):
        cleaned = super().clean()
        for name in self.fields:
            if len(self.data.getlist(name)) > 1:
                self.add_error(name, "Informe este filtro uma única vez.")
        return cleaned


def _niche_key(raw):
    normalized = raw.strip().casefold()
    if not normalized:
        return "unassigned", "Sem nicho informado"
    for code, label in PRACTICE_AREA_LABELS.items():
        if normalized in (code.casefold(), label.casefold()):
            return code, label
    return "legacy:" + normalized, raw.strip()


def _niche_catalog(queryset, organization):
    """Combine legacy labels/codes without exposing inaccessible matter areas."""
    labels = dict(practice_area_choices(organization))
    raw_values = defaultdict(set)
    for raw in queryset.order_by().values_list("matter__area", flat=True).distinct():
        key, label = _niche_key(raw)
        labels[key] = label
        raw_values[key].add(raw)
    choices = sorted(labels.items(), key=lambda pair: (pair[0] == "unassigned", pair[1].casefold()))
    return choices, raw_values


def _url(values, **changes):
    query = QueryDict(mutable=True)
    for name in ("q", "status", "niche", "owner", "sort", "per_page"):
        value = values.get(name)
        if value not in (None, ""):
            query[name] = str(value.pk if name == "owner" else value)
    for name, value in changes.items():
        if value in (None, ""):
            query.pop(name, None)
        else:
            query[name] = str(value)
    return reverse("legal:list", args=["cases"]) + ("?" + query.urlencode() if query else "")


@require_GET
def directory(request):
    # Import locally because record_list dispatches here from views.py.
    from .views import organization_required
    return organization_required(_directory)(request)


def _directory(request):
    from .views import can_edit, scoped_queryset

    matters = visible_matters(request.user, request.organization)
    base = scoped_queryset(request.user, request.organization, CourtCase).filter(matter__in=matters)
    owners = get_user_model().objects.filter(
        pk__in=base.order_by().values("matter__owner_id"), is_active=True,
        memberships__organization=request.organization, memberships__is_active=True,
        memberships__role__in=INTERNAL_ROLES,
    ).distinct().order_by("first_name", "last_name", "email", "pk")
    niches, niche_values = _niche_catalog(base, request.organization)
    form = DirectoryFilters(request.GET, owners=owners, niches=niches)
    valid = form.is_valid()
    values = form.cleaned_data if valid else {}
    filtered = base if valid else base.none()
    if values.get("q"):
        term = values["q"]
        filtered = filtered.filter(
            Q(number__icontains=term) | Q(matter__client__name__icontains=term)
            | Q(matter__title__icontains=term) | Q(court__icontains=term)
            | Q(opposing_party__icontains=term)
        )
    if values.get("owner"):
        filtered = filtered.filter(matter__owner=values["owner"])
    if values.get("niche"):
        filtered = filtered.filter(matter__area__in=niche_values[values["niche"]])

    # These navigation counts deliberately precede the situation filter.
    # The visible caption explains the scope, and selecting a card replaces
    # that one filter while preserving search, owner, niche, and ordering.
    totals = filtered.aggregate(
        total=Count("pk"), active=Count("pk", filter=Q(matter__status="active")),
        waiting=Count("pk", filter=Q(matter__status="waiting")),
        closed=Count("pk", filter=Q(matter__status="closed")),
    )
    stats = [
        {"key": key, "value": totals[key], "label": label,
         "selected": values.get("status", "") == status, "url": _url(values, status=status)}
        for key, label, status in (
            ("total", "Todos os processos", ""),
            ("active", "Pasta em andamento", "active"),
            ("waiting", "Pasta aguardando", "waiting"),
            ("closed", "Pasta encerrada", "closed"),
        )
    ]
    if values.get("status"):
        filtered = filtered.filter(matter__status=values["status"])

    distribution = {}
    for item in filtered.order_by().values("matter__area").annotate(total=Count("pk")):
        key, label = _niche_key(item["matter__area"])
        bucket = distribution.setdefault(key, {"key": key, "label": label, "count": 0})
        bucket["count"] += item["total"]
    distribution = sorted(distribution.values(), key=lambda item: (-item["count"], item["label"].casefold()))
    result_total = sum(item["count"] for item in distribution)
    for item in distribution:
        item["percent"] = round(item["count"] * 100 / result_total)
        item["width"] = f'{item["count"] * 100 / result_total:.2f}'
        item["url"] = _url(values, niche=item["key"])
        item["selected"] = values.get("niche") == item["key"]

    records = filtered.select_related("matter", "matter__client", "matter__owner").order_by(*SORTS[values.get("sort", "newest")])
    paginator = Paginator(records, values.get("per_page", 25))
    try:
        page = paginator.page(values.get("page", 1))
    except EmptyPage:
        form.add_error("page", "Esta página não existe. Volte à primeira página ou revise os filtros.")
        valid = False
        page = Paginator(base.none(), 25).page(1)
    rows = []
    for case in page.object_list:
        rows.append({
            "record": case, "matter": case.matter,
            "url": reverse("legal:detail", args=[case.matter_id]),
            "edit_url": reverse("legal:edit", args=["cases", case.pk]) if can_edit(request) else "",
            "owner": _user_label(case.matter.owner),
            "area": _niche_key(case.matter.area)[1],
        })
    context = {
        "page_title": "Processos", "active_nav": "cases", "title": "Processos", "module": "cases",
        "filter_form": form, "filters_valid": valid, "case_stats": stats if valid else [],
        "case_distribution": distribution if valid else [], "case_rows": rows,
        "page_obj": page, "result_total": result_total if valid else 0,
        "matter_total": filtered.values("matter_id").distinct().count() if valid else 0,
        "has_filters": any(values.get(field) for field in ("q", "status", "owner", "niche")),
        "can_create": can_edit(request), "create_url": reverse("legal:create", args=["cases"]),
        "clear_url": reverse("legal:list", args=["cases"]), "first_url": _url(values),
        "previous_url": _url(values, page=page.previous_page_number()) if page.has_previous() else "",
        "next_url": _url(values, page=page.next_page_number()) if page.has_next() else "",
        "module_template": "legal/case_directory.html", "module_rows": rows, "module_stats": stats if valid else [],
    }
    return render(request, "legal/case_directory.html", context, status=200 if valid else 400)
