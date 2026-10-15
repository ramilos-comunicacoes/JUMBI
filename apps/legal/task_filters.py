from datetime import timedelta

from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Membership
from apps.core.niches import practice_area_choices
from .models import Task
from .niches import filter_niche


BOARD_GROUPS = [("overdue", "Atrasadas"), ("todo", "A fazer"), ("doing", "Em andamento"), ("done", "Finalizadas")]


def pending_tasks():
    return ~Q(status__in=[Task.Status.DONE, Task.Status.CANCELLED])


def filter_task_group(queryset, group, *, today=None):
    """Display groups never replace the task's actual audited status."""
    today = today or timezone.localdate()
    if group == "overdue":
        return queryset.filter(pending_tasks(), due_date__lt=today)
    if group == "todo":
        return queryset.filter(status=Task.Status.TODO, due_date__gte=today)
    if group == "doing":
        return queryset.filter(status__in=[Task.Status.DOING, Task.Status.IN_REVIEW, Task.Status.BLOCKED], due_date__gte=today)
    if group == "done":
        return queryset.filter(status__in=[Task.Status.DONE, Task.Status.CANCELLED])
    return queryset


def filter_task_period(queryset, period, *, today=None):
    today = today or timezone.localdate()
    if period in {"pending", "today", "week", "overdue"}:
        queryset = queryset.filter(pending_tasks())
    if period == "today":
        return queryset.filter(due_date=today)
    if period == "week":
        return queryset.filter(due_date__gte=today, due_date__lte=today + timedelta(days=6))
    if period == "overdue":
        return queryset.filter(due_date__lt=today)
    if period == "completed_month":
        return queryset.filter(status=Task.Status.DONE, completed_at__date__gte=today.replace(day=1), completed_at__date__lte=today)
    return queryset


def filter_tasks(queryset, form, *, include_period=True, today=None):
    """Filter only an already authorized queryset; malformed filters fail closed."""
    if not form.is_valid():
        return queryset.none()
    data = form.cleaned_data
    if data["q"]:
        queryset = queryset.filter(Q(title__icontains=data["q"]) | Q(description__icontains=data["q"]) | Q(matter__title__icontains=data["q"]))
    if data["owner"]:
        queryset = queryset.filter(owner_id=data["owner"])
    if data["priority"]:
        queryset = queryset.filter(priority=data["priority"])
    queryset = filter_niche(queryset, data["niche"], form.fields["niche"].choices, relation="matter__")
    if include_period:
        queryset = filter_task_period(queryset, data["period"], today=today)
    if data.get("board_group"):
        queryset = filter_task_group(queryset, data["board_group"], today=today)
    if data.get("status"):
        queryset = queryset.filter(status=data["status"])
    return queryset


class TaskBoardFilterForm(forms.Form):
    q = forms.CharField(label="Buscar", max_length=120, required=False)
    owner = forms.ChoiceField(label="Responsável", required=False)
    priority = forms.ChoiceField(label="Prioridade", required=False, choices=[("", "Todas"), *Task.Priority.choices])
    niche = forms.ChoiceField(label="Nicho", required=False)
    period = forms.ChoiceField(label="Recorte de trabalho", required=False, choices=[("", "Todas as entregas"), ("pending", "Em aberto"), ("today", "Para hoje · em aberto"), ("week", "Próximos 7 dias · em aberto"), ("overdue", "Atrasadas"), ("completed_month", "Concluídas neste mês")])

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        members = Membership.objects.filter(organization=request.organization, is_active=True, user__is_active=True, role__in=["owner", "manager", "operator", "viewer"]).select_related("user").order_by("user__email")
        self.fields["owner"].choices = [("", "Toda a equipe"), *((str(m.user_id), m.user.get_full_name() or m.user.email) for m in members)]
        self.fields["niche"].choices = [("", "Todos os nichos"), *practice_area_choices(request.organization)]


class TaskListFilterForm(TaskBoardFilterForm):
    board_group = forms.ChoiceField(label="Coluna do quadro", required=False, choices=[("", "Todas as colunas"), *BOARD_GROUPS])
    status = forms.ChoiceField(label="Etapa da tarefa", required=False, choices=[("", "Todas as etapas"), *Task.Status.choices])
