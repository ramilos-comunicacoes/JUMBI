"""Personal routine and workspace for team members.

Gives each collaborator a focused 'mini-system' within the office:
- My activities & delegated tasks
- My authorized matters
- My upcoming deadlines with urgency indicators
- My pending messages
- My agenda
- My individual goals
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.models import Membership, User
from apps.performance.services import dashboard_goals
from .models import Appointment, ClientContact, Deadline, Matter, Task
from .services import audit, visible_matters
from .views import can_edit, organization_required


@organization_required
@require_http_methods(["GET"])
def my_routine(request):
    today = timezone.localdate()
    user = request.user
    org = request.organization

    tasks = Task.objects.filter(organization=org, owner=user).exclude(
        status__in=[Task.Status.DONE, Task.Status.CANCELLED]
    ).select_related("matter", "delegated_by", "reviewer").order_by("due_date")

    deadlines = Deadline.objects.filter(organization=org, owner=user).exclude(
        status=Deadline.Status.FULFILLED
    ).select_related("matter").order_by("due_date")

    contacts = ClientContact.objects.filter(organization=org, actor=user).exclude(
        status=ClientContact.Status.COMPLETED_MANUAL
    ).select_related("matter", "contact").order_by("-created_at")[:10]

    matters = visible_matters(user, org).filter(
        models_q := (models_q_filter(user))
    ).distinct().select_related("client")[:8]

    appointments = Appointment.objects.filter(
        organization=org, owner=user, ends_at__gte=timezone.now()
    ).select_related("matter").order_by("starts_at")[:5]

    goals = dashboard_goals(user, org)

    # Active colleagues for delegation / reassignment options
    colleagues = User.objects.filter(
        memberships__organization=org,
        memberships__is_active=True,
        is_active=True,
    ).exclude(memberships__role="client").distinct().order_by("first_name", "email")

    return render(request, "legal/my_routine.html", {
        "title": "Minha Rotina",
        "page_title": "Minha Rotina",
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
        "urgent_deadlines_count": sum(1 for d in deadlines if d.urgency_level == "urgent"),
        "pending_deadlines_count": sum(1 for d in deadlines if d.urgency_level == "pending"),
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
    new_owner_id = request.POST.get("new_owner")
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
        memberships__is_active=True,
        is_active=True,
    )

    tasks = Task.objects.select_for_update().filter(
        pk__in=task_ids,
        organization=request.organization,
    ).exclude(status__in=[Task.Status.DONE, Task.Status.CANCELLED])

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
