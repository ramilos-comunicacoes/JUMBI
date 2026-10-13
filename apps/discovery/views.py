from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import Membership
from apps.legal.views import can_edit, organization_required
from .forms import SaveSearchForm, SearchForm
from .models import SavedSearch
from .services import result_card, search_sets, search_url


def personal_searches(request):
    return SavedSearch.objects.filter(organization=request.organization, user=request.user)


@organization_required
@require_GET
def search(request):
    form = SearchForm(request.GET if "q" in request.GET else None, organization=request.organization)
    groups, cards, total, page = [], [], 0, None
    if form.is_bound and form.is_valid():
        groups = search_sets(request, form.cleaned_data)
        total = sum(group["count"] for group in groups)
        page = Paginator(range(total), 20).get_page(request.GET.get("page"))
        start, stop = (page.number - 1) * 20, page.number * 20
        offset = 0
        for group in groups:
            lo, hi = max(0, start - offset), min(group["count"], stop - offset)
            if lo < hi:
                cards.append({"label": group["label"], "kind": group["key"], "items": [
                    result_card(obj, group["key"], editable=can_edit(request)) for obj in group["records"][lo:hi]
                ]})
            offset += group["count"]
            group["url"] = search_url(query=form.cleaned_data["q"], kind=group["key"], niche=form.cleaned_data["niche"])
    criteria = form.cleaned_data if form.is_bound and form.is_valid() else {}
    pagination = {}
    if page and criteria:
        for direction, available, number in [("previous", page.has_previous(), page.number - 1), ("next", page.has_next(), page.number + 1)]:
            if available:
                pagination[direction] = search_url(query=criteria["q"], kind=criteria["kind"], niche=criteria["niche"], page=number)
    return render(request, "discovery/search.html", {
        "page_title": "Busca unificada", "active_nav": "search", "form": form,
        "searched": bool(criteria), "groups": groups, "result_groups": cards, "total": total,
        "page": page, "pagination": pagination, "criteria": criteria,
        "saved_searches": personal_searches(request),
    })


@organization_required
@require_POST
def save(request):
    form = SaveSearchForm(request.POST, organization=request.organization)
    if not form.is_valid():
        messages.error(request, "Informe um nome, um termo de ao menos dois caracteres e filtros válidos para salvar.")
        return redirect("discovery:search")
    data = form.cleaned_data
    with transaction.atomic():
        # Serializes the per-member quota and rechecks a revocation while saving.
        member = Membership.objects.select_for_update().filter(pk=request.membership.pk, is_active=True, role__in=["owner", "manager", "operator", "viewer"]).first()
        if member is None:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        searches = personal_searches(request)
        if searches.count() >= 12:
            messages.error(request, "Você já tem 12 buscas salvas. Exclua uma antes de salvar outra.")
        elif searches.filter(name__iexact=data["name"]).exists():
            messages.error(request, "Já existe uma busca sua com esse nome. Escolha outro nome.")
        else:
            try:
                with transaction.atomic():
                    SavedSearch.objects.create(organization=request.organization, user=request.user,
                        name=data["name"], query=data["q"], kind=data["kind"], niche=data["niche"])
                messages.success(request, "Busca salva. Os resultados sempre refletem seus acessos atuais.")
            except IntegrityError:
                messages.error(request, "Esta busca já foi salva.")
    return redirect(search_url(query=data["q"], kind=data["kind"], niche=data["niche"]))


@organization_required
@require_GET
def open_saved(request, pk):
    item = get_object_or_404(personal_searches(request), pk=pk)
    return redirect(search_url(query=item.query, kind=item.kind, niche=item.niche))


@organization_required
@require_POST
def delete(request, pk):
    get_object_or_404(personal_searches(request), pk=pk).delete()
    messages.success(request, "Busca removida dos seus atalhos.")
    return redirect("discovery:search")
