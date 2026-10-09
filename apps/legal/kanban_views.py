"""Accessible task board with server-validated, audited moves."""
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.models import Membership
from .models import Task
from .niches import filter_niche, niche_selection
from .services import move_task
from .views import can_edit, organization_required, scoped_queryset


class MoveForm(forms.Form):
    destination = forms.ChoiceField(label="Mover para", choices=Task.Status.choices)
    expected_status = forms.ChoiceField(choices=Task.Status.choices, widget=forms.HiddenInput)
    note = forms.CharField(label="Evidência de conclusão / motivo da reabertura", required=False, max_length=4000,
                           widget=forms.Textarea(attrs={"rows": 3}), help_text="Obrigatório ao concluir ou reabrir uma tarefa.")


@organization_required
@require_GET
def board(request):
    tasks = scoped_queryset(request.user, request.organization, Task).select_related("matter", "owner")
    niche, choices = niche_selection(request)
    tasks = filter_niche(tasks, niche, choices, relation="matter__")
    query = request.GET.get("q", "").strip()[:200]
    if query:
        tasks = tasks.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(matter__title__icontains=query))
    members = Membership.objects.filter(organization=request.organization, is_active=True, user__is_active=True).select_related("user")
    owner = request.GET.get("owner", "")
    if owner.isdecimal() and members.filter(user_id=owner).exists():
        tasks = tasks.filter(owner_id=owner)
    else:
        owner = ""
    priority = request.GET.get("priority", "")
    if priority in Task.Priority.values:
        tasks = tasks.filter(priority=priority)
    else:
        priority = ""
    columns = []
    today = timezone.localdate()
    for code, label in [("overdue", "Atrasadas"), *Task.Status.choices]:
        if code == "overdue":
            rows = tasks.exclude(status=Task.Status.DONE).filter(due_date__lt=today)
        else:
            rows = tasks.filter(status=code)
            if code != Task.Status.DONE:
                rows = rows.filter(due_date__gte=today)
        rows = rows.order_by("due_date", "pk")
        # Keep the board light without pretending a truncated count is a total.
        count = rows.count()
        columns.append({"code": code, "label": label, "count": count, "tasks": list(rows[:100]), "truncated": count > 100})
    return render(request, "legal/kanban.html", {
        "page_title": "Quadro de tarefas", "active_nav": "tasks", "columns": columns,
        "q": query, "owner_filter": owner, "priority_filter": priority, "niche": niche,
        "niche_choices": choices, "members": members, "priorities": Task.Priority.choices,
        "can_edit": can_edit(request), "today": today,
    })


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
