"""Personal routine and workspace for team members.

Gives each collaborator a focused 'mini-system' within the office:
- My activities & delegated tasks
- My authorized matters
- My upcoming deadlines with urgency indicators
- My pending messages
- My agenda
- My individual goals
"""

from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.models import Membership, User
from apps.core.niches import practice_area_values
from apps.performance.models import ScoreEvent
from apps.performance.services import dashboard_goals
from .models import AdministrativeDemand, Appointment, ClientContact, Deadline, Matter, Task
from .services import audit, visible_matters
from .views import can_edit, organization_required, scoped_queryset


@organization_required
@require_http_methods(["GET"])
def my_routine(request):
    today = timezone.localdate()
    user = request.user
    org = request.organization

    tasks = scoped_queryset(user, org, Task).filter(owner=user).exclude(
        status__in=[Task.Status.DONE, Task.Status.CANCELLED]
    ).select_related("matter", "delegated_by", "reviewer").order_by("due_date")

    deadlines = scoped_queryset(user, org, Deadline).filter(owner=user).exclude(
        status=Deadline.Status.FULFILLED
    ).select_related("matter").order_by("due_date")

    contacts = scoped_queryset(user, org, ClientContact).filter(actor=user).exclude(
        status=ClientContact.Status.COMPLETED_MANUAL
    ).select_related("matter", "contact").order_by("-created_at")[:10]

    user_visible_matters = visible_matters(user, org)
    matters = user_visible_matters.filter(
        models_q := (models_q_filter(user))
    ).distinct().select_related("client")[:8]

    appointments = scoped_queryset(user, org, Appointment).filter(
        owner=user, ends_at__gte=timezone.now()
    ).select_related("matter").order_by("starts_at")[:5]

    goals = dashboard_goals(user, org)

    # Active colleagues for delegation / reassignment options
    colleagues = User.objects.filter(
        memberships__organization=org,
        memberships__is_active=True,
        is_active=True,
        memberships__role__in=["owner", "manager", "operator"],
    ).distinct().order_by("first_name", "email")

    # --- COLLABORATOR PRODUCTIVITY & SCORING ---
    score_events = ScoreEvent.objects.filter(organization=org, user=user)
    earned_pts = score_events.filter(is_reversal=False).aggregate(total=Sum("points"))["total"] or Decimal("0.00")
    reversed_pts = score_events.filter(is_reversal=True).aggregate(total=Sum("points"))["total"] or Decimal("0.00")
    net_score = earned_pts - reversed_pts
    scored_deliveries = score_events.filter(is_reversal=False).count()

    # Tasks completed this month
    start_of_month = today.replace(day=1)
    completed_tasks_month = scoped_queryset(user, org, Task).filter(
        owner=user,
        status=Task.Status.DONE,
    ).filter(
        Q(completed_at__date__gte=start_of_month) | Q(completed_at__isnull=True, created_at__date__gte=start_of_month)
    ).count()

    # Deadlines punctuality rate
    all_user_deadlines = scoped_queryset(user, org, Deadline).filter(owner=user)
    fulfilled_deadlines = all_user_deadlines.filter(status=Deadline.Status.FULFILLED).count()
    overdue_deadlines_count = sum(1 for d in deadlines if d.urgency_level == "overdue")
    urgent_deadlines_count = sum(1 for d in deadlines if d.urgency_level == "urgent")
    pending_deadlines_count = sum(1 for d in deadlines if d.urgency_level == "pending")

    total_evaluated = all_user_deadlines.count()
    punctuality_rate = (
        round((fulfilled_deadlines / total_evaluated) * 100)
        if total_evaluated > 0
        else None
    )

    # --- PREVIDENCIÁRIO HUB (INSS, PROTOCOLOS, BENEFÍCIOS, PETIÇÕES) ---
    prev_area_values = practice_area_values("previdenciario")
    prev_demands = AdministrativeDemand.objects.filter(
        organization=org,
        matter__in=user_visible_matters,
    ).select_related("matter", "contact", "assigned_to")

    my_prev_demands = prev_demands.filter(
        Q(assigned_to=user) | Q(matter__owner=user) | Q(matter__members=user)
    ).distinct()

    # If collaborator has no specific demands assigned yet, fallback to visible demands so dashboard is informative
    display_demands = my_prev_demands if my_prev_demands.exists() else prev_demands

    prev_total_active = display_demands.filter(
        status__in=[AdministrativeDemand.Status.PENDING, AdministrativeDemand.Status.REQUIREMENT, AdministrativeDemand.Status.SUSPENDED]
    ).count()
    prev_requirement_count = display_demands.filter(status=AdministrativeDemand.Status.REQUIREMENT).count()
    prev_pending_count = display_demands.filter(status=AdministrativeDemand.Status.PENDING).count()
    prev_concluded_count = display_demands.filter(status=AdministrativeDemand.Status.CONCLUDED).count()
    prev_rejected_count = display_demands.filter(status=AdministrativeDemand.Status.REJECTED).count()

    # High priority demands: Requirements and pending analysis
    priority_demands = display_demands.filter(
        status__in=[AdministrativeDemand.Status.REQUIREMENT, AdministrativeDemand.Status.PENDING]
    ).order_by("-status", "-updated_at")[:6]

    # Previdenciário Petitions & Specific Tasks
    prev_tasks = tasks.filter(
        Q(matter__area__in=prev_area_values) |
        Q(title__icontains="petição") |
        Q(title__icontains="inss") |
        Q(title__icontains="exigência") |
        Q(title__icontains="recurso") |
        Q(title__icontains="benefício") |
        Q(title__icontains="aposentadoria") |
        Q(title__icontains="bpc") |
        Q(title__icontains="laudo")
    )[:8]

    return render(request, "legal/my_routine.html", {
        "title": "Minha Rotina & Produtividade",
        "page_title": "Minha Rotina & Produtividade",
        "active_nav": "my_routine",
        "today": today,
        "tasks": tasks,
        "deadlines": deadlines,
        "contacts": contacts,
        "matters": matters,
        "appointments": appointments,
        "goals": goals,
        "colleagues": colleagues,
        "can_edit": can_edit(request),
        "urgent_deadlines_count": urgent_deadlines_count,
        "pending_deadlines_count": pending_deadlines_count,
        "overdue_deadlines_count": overdue_deadlines_count,
        # Productivity & Ranking
        "net_score": net_score,
        "scored_deliveries": scored_deliveries,
        "completed_tasks_month": completed_tasks_month,
        "fulfilled_deadlines": fulfilled_deadlines,
        "punctuality_rate": punctuality_rate,
        # Previdenciário Hub
        "prev_total_active": prev_total_active,
        "prev_requirement_count": prev_requirement_count,
        "prev_pending_count": prev_pending_count,
        "prev_concluded_count": prev_concluded_count,
        "prev_rejected_count": prev_rejected_count,
        "priority_demands": priority_demands,
        "prev_tasks": prev_tasks,
    })


def models_q_filter(user):
    from django.db.models import Q
    return Q(owner=user) | Q(members=user)


@organization_required
@require_http_methods(["POST"])
@transaction.atomic
def bulk_reassign_tasks(request):
    """Reassign selected open tasks to another collaborator with an explicit audit trail."""
    if not can_edit(request):
        raise PermissionDenied("Você não tem permissão para redistribuir atividades.")

    task_ids = request.POST.getlist("task_ids")
    if len(task_ids) > 100 or any(not value.isdecimal() for value in task_ids):
        messages.error(request, "Selecione até 100 tarefas válidas.")
        return redirect("legal:my_routine")
    new_owner_id = request.POST.get("new_owner", "")
    if not new_owner_id.isdecimal():
        new_owner_id = None
    reason = request.POST.get("reason", "").strip()

    if not task_ids:
        messages.error(request, "Selecione pelo menos uma tarefa para transferir.")
        return redirect(reverse("legal:my_routine"))

    if not new_owner_id:
        messages.error(request, "Selecione o novo responsável.")
        return redirect(reverse("legal:my_routine"))

    if not reason:
        messages.error(request, "Informe o motivo da redistribuição.")
        return redirect(reverse("legal:my_routine"))

    new_owner = get_object_or_404(
        User,
        pk=new_owner_id,
        memberships__organization=request.organization,
        memberships__role__in=["owner", "manager", "operator"],
        memberships__is_active=True,
        is_active=True,
    )

    tasks = scoped_queryset(request.user, request.organization, Task).select_for_update().filter(
        pk__in=task_ids,
        organization=request.organization,
    ).exclude(status__in=[Task.Status.DONE, Task.Status.CANCELLED])

    tasks = list(tasks)
    for task in tasks:
        if task.matter_id and not visible_matters(new_owner, request.organization).filter(pk=task.matter_id).exists():
            messages.error(request, "O novo responsável não possui acesso a todas as pastas selecionadas.")
            return redirect("legal:my_routine")
    count = 0
    for task in tasks:
        prev_owner = task.owner
        if prev_owner == new_owner:
            continue
        task.owner = new_owner
        task.save(update_fields=["owner"])
        audit(
            organization=request.organization,
            actor=request.user,
            action="task.reassigned",
            obj=task,
            description=f"Transferida de {prev_owner.get_full_name() or prev_owner.email} para {new_owner.get_full_name() or new_owner.email}. Motivo: {reason}",
        )
        count += 1

    messages.success(request, f"{count} tarefa(s) redistribuída(s) com sucesso para {new_owner.get_full_name() or new_owner.email}.")
    return redirect(reverse("legal:my_routine"))
