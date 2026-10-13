from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse

from apps.core.niches import practice_area_choices
from apps.legal.models import Contact, Matter
from apps.legal.niches import filter_niche
from apps.legal.services import visible_matters
from apps.legal.views import MODULES, scoped_queryset

from .forms import KINDS


def search_url(*, query, kind="", niche="", **extra):
    return reverse("discovery:search") + "?" + urlencode({"q": query, "kind": kind, "niche": niche, **extra})


def search_sets(request, criteria):
    """Each query starts from the same live authorization as its source module."""
    choices = practice_area_choices(request.organization)
    query = criteria["q"]
    groups = []
    for kind, label in KINDS[1:]:
        if criteria["kind"] and criteria["kind"] != kind:
            continue
        module = MODULES[kind]
        records = scoped_queryset(request.user, request.organization, module["model"])
        niche = criteria["niche"]
        if kind == "matters":
            records = filter_niche(records, niche, choices).select_related("client")
        elif kind == "contacts":
            if niche:
                clients = filter_niche(visible_matters(request.user, request.organization), niche, choices).values("client_id")
                records = records.filter(pk__in=clients)
        else:
            records = filter_niche(records, niche, choices, relation="matter__").select_related("matter")
        # AND between words, OR between module fields. Bounded input limits SQL size.
        for term in query.split()[:8]:
            match = Q()
            for field in module["search"]:
                match |= Q(**{field + "__icontains": term})
            records = records.filter(match)
        records = records.order_by("pk")
        groups.append({"key": kind, "label": label, "records": records, "count": records.count()})
    return groups


def result_card(obj, kind, *, editable):
    title = str(obj)
    subtitle = ""
    if isinstance(obj, Contact):
        subtitle = " · ".join(filter(None, [obj.get_kind_display(), obj.email, obj.phone]))
    elif isinstance(obj, Matter):
        subtitle = " · ".join(filter(None, [obj.client.name if obj.client else "", obj.get_status_display()]))
    elif getattr(obj, "matter", None):
        subtitle = obj.matter.title
    if kind == "matters":
        url = reverse("legal:detail", args=[obj.pk])
    elif editable:
        url = reverse("legal:edit", args=[kind, obj.pk])
    elif getattr(obj, "matter_id", None):
        url = reverse("legal:detail", args=[obj.matter_id])
    else:
        url = reverse("legal:list", args=[kind]) + "?" + urlencode({"q": title})
    return {"title": title, "subtitle": subtitle, "url": url, "kind": kind, "id": obj.pk,
            "action": "Abrir pasta" if kind == "matters" or (not editable and getattr(obj, "matter_id", None)) else "Abrir cadastro" if editable else "Ver na lista"}
