"""Accessible task board with server-validated, audited moves."""
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.models import Membership
from .models import Task
from .niches import niche_selection
from .services import move_task
from .task_filters import BOARD_GROUPS, TaskBoardFilterForm, filter_task_group, filter_task_period, filter_tasks, pending_tasks
from .views import can_edit, organization_required, scoped_queryset


class MoveForm(forms.Form):
    destination = forms.ChoiceField(label="Mover para", choices=Task.Status.choices)
    expected_status = forms.ChoiceField(choices=Task.Status.choices, widget=forms.HiddenInput)
    note = forms.CharField(label="Evidência de conclusão / motivo da mudança", required=False, max_length=4000,
                           widget=forms.Textarea(attrs={"rows": 3}), help_text="Obrigatório ao concluir, cancelar, reabrir ou reativar uma tarefa.")


@organization_required
@require_GET
def board(request):
    tasks = scoped_queryset(request.user, request.organization, Task).select_related("matter", "owner")
    form = TaskBoardFilterForm(request.GET, request=request)
    valid = form.is_valid()
    niche, choices = niche_selection(request)
    tasks = filter_tasks(tasks, form, include_period=False)
    query = form.cleaned_data.get("q", "") if valid else ""
    members = Membership.objects.filter(organization=request.organization, is_active=True, user__is_active=True, role__in=["owner", "manager", "operator", "viewer"]).select_related("user")
    owner = form.cleaned_data.get("owner", "") if valid else ""
    priority = form.cleaned_data.get("priority", "") if valid else ""
    columns = []
    today = timezone.localdate()
    month_start = today.replace(day=1)
    pending = pending_tasks()
    completed_month = Q(status=Task.Status.DONE, completed_at__date__gte=month_start, completed_at__date__lte=today)
    totals = tasks.aggregate(pending=Count("pk", filter=pending), overdue=Count("pk", filter=pending & Q(due_date__lt=today)), completed_month=Count("pk", filter=completed_month))
    metrics = []
    for key, label in [("pending", "Entregas em aberto"), ("overdue", "Entregas atrasadas"), ("completed_month", "Concluídas neste mês")]:
        params = request.GET.copy()
        params.pop("page", None)
        params["period"] = key
        metrics.append({"label": label, "value": totals[key], "url": reverse("legal:kanban") + "?" + params.urlencode()})
    period = form.cleaned_data.get("period", "") if valid else ""
    tasks = filter_task_period(tasks, period, today=today)
    for code, label in BOARD_GROUPS:
        rows = filter_task_group(tasks, code, today=today)
        rows = rows.order_by("due_date", "pk")
        # Keep the board light without pretending a truncated count is a total.
        count = rows.count()
        params = request.GET.copy()
        for name in list(params):
            if name not in form.fields:
                params.pop(name, None)
        params["board_group"] = code
        columns.append({"code": code, "label": label, "count": count, "tasks": list(rows[:100]), "truncated": count > 100,
                        "list_url": reverse("legal:list", args=["tasks"]) + "?" + params.urlencode()})
    return render(request, "legal/kanban.html", {
        "page_title": "Quadro de tarefas", "active_nav": "tasks", "columns": columns,
        "q": query, "owner_filter": owner, "priority_filter": priority, "niche": niche,
        "niche_choices": choices, "members": members, "priorities": Task.Priority.choices,
        "can_edit": can_edit(request), "today": today,
        "board_filter_form": form, "task_metrics": metrics,
        "task_status_choices": Task.Status.choices,
        "has_active_filters": any(request.GET.get(key, "").strip() for key in form.fields),
    }, status=200 if valid else 400)


@organization_required
@require_http_methods(["GET", "POST"])
def move(request, pk):
    if not can_edit(request):
        raise PermissionDenied("Seu perfil permite somente consulta.")
    task = get_object_or_404(scoped_queryset(request.user, request.organization, Task), pk=pk)
    form = MoveForm(request.POST if request.method == "POST" else None,
                    initial={"expected_status": task.status, "destination": task.status})
    wants_json = request.headers.get("Accept") == "application/json"
    if request.method == "POST" and form.is_valid():
        try:
            task = move_task(task=task, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if wants_json:
                return JsonResponse({"ok": True, "status": task.status})
            messages.success(request, "Tarefa movimentada. O histórico foi preservado.")
            return redirect("legal:kanban")
    if request.method == "POST" and wants_json:
        return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)
    return render(request, "legal/form.html", {
        "page_title": "Mover tarefa", "title": "Mover tarefa", "subtitle": task.title,
        "active_nav": "tasks", "form": form, "cancel_url": reverse("legal:kanban"), "submit_label": "Salvar movimentação",
    })
