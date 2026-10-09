from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.billing.services import require_access
from apps.core.niches import practice_area_choices
from apps.legal.views import organization_required
from .forms import GoalForm, ProgressForm
from .models import Goal
from .services import can_manage_goals, goal_card, record_progress, save_goal, visible_goals


@organization_required
@require_GET
def goal_list(request):
    require_access(request.organization)
    choices = practice_area_choices(request.organization)
    niche = request.GET.get("niche", "")
    if niche and niche not in dict(choices):
        raise Http404("Área de atuação não configurada neste escritório.")
    archived = request.GET.get("archived") == "1"
    goals = visible_goals(request.user, request.organization).filter(archived=archived).select_related("organization", "owner")
    if niche:
        goals = goals.filter(niche=niche)
    page = Paginator(goals, 12).get_page(request.GET.get("page"))
    return render(request, "performance/list.html", {
        "page_title": "Metas de desempenho", "active_nav": "goals", "page": page,
        "cards": [goal_card(goal, request.user) for goal in page], "niche_choices": choices,
        "selected_niche": niche, "archived": archived, "can_manage_goals": can_manage_goals(request.user, request.organization),
    })


@organization_required
@require_http_methods(["GET", "POST"])
def goal_edit(request, pk=None):
    require_access(request.organization)
    if not can_manage_goals(request.user, request.organization):
        raise PermissionDenied("Somente a direção e a gestão podem cadastrar ou atualizar metas.")
    goal = get_object_or_404(visible_goals(request.user, request.organization), pk=pk) if pk else None
    initial = {"starts_on": timezone.localdate(), "ends_on": timezone.localdate()}
    form = GoalForm(request.POST or None, instance=goal, initial=initial if goal is None else None, organization=request.organization, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            save_goal(actor=request.user, organization=request.organization, data=form.cleaned_data, goal_id=pk)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Meta salva. O progresso dos indicadores automáticos acompanha os registros do escritório.")
            return redirect("performance:list")
    return render(request, "performance/form.html", {"form": form, "page_title": "Editar meta" if pk else "Nova meta", "active_nav": "goals"})


@organization_required
@require_http_methods(["GET", "POST"])
def goal_progress(request, pk):
    require_access(request.organization)
    if not can_manage_goals(request.user, request.organization):
        raise PermissionDenied("Somente a direção e a gestão podem atualizar o progresso.")
    goal = get_object_or_404(visible_goals(request.user, request.organization), pk=pk, metric=Goal.Metric.MANUAL)
    form = ProgressForm(request.POST or None, initial={"value": goal.manual_value})
    if request.method == "POST" and form.is_valid():
        try:
            record_progress(actor=request.user, organization=request.organization, goal_id=goal.pk, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Progresso atualizado com evidência no histórico.")
            return redirect("performance:list")
    return render(request, "performance/form.html", {
        "form": form, "page_title": f"Atualizar progresso · {goal.title}", "active_nav": "goals",
        "goal": goal, "history": goal.updates.select_related("actor")[:20],
    })
