"""One selection across dashboards and lists; old area labels remain usable."""
from django.db.models import Q
from apps.core.niches import practice_area_choices


def niche_selection(request):
    choices = practice_area_choices(request.organization)
    requested = request.GET.get("niche", "")
    selected = requested if requested in dict(choices) else ""
    return selected, choices


def filter_niche(queryset, niche, choices, *, relation=""):
    if not niche:
        return queryset
    label = dict(choices).get(niche)
    if label is None:
        return queryset.none()
    field = f"{relation}area__iexact"
    return queryset.filter(Q(**{field: niche}) | Q(**{field: label}))
