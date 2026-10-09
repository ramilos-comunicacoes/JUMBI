from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import CharField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from apps.billing.services import has_advanced, require_access
from apps.core.models import Membership
from apps.core.niches import practice_area_values
from apps.legal.models import AuditEvent, Matter, Payment, Task
from apps.legal.services import audit, visible_matters
from .models import Goal, GoalUpdate


def can_manage_goals(user, organization):
    return bool(user.is_authenticated and user.is_active and organization and organization.status == "active" and Membership.objects.filter(
        user=user, organization=organization, is_active=True, role__in=["owner", "manager"],
    ).exists())


def visible_goals(user, organization):
    if not user.is_authenticated or not user.is_active or not organization or organization.status != "active" or not Membership.objects.filter(user=user, organization=organization, is_active=True).exists():
        return Goal.objects.none()
    queryset = Goal.objects.filter(organization=organization)
    if not can_manage_goals(user, organization) or not has_advanced(organization):
        queryset = queryset.exclude(metric=Goal.Metric.REVENUE)
    return queryset


def _authorize(actor, organization, metric):
    require_access(organization, advanced=metric == Goal.Metric.REVENUE)
    if not can_manage_goals(actor, organization):
        raise PermissionDenied("Somente a direção e a gestão podem cadastrar ou atualizar metas.")


def goal_progress(goal, user):
    """Calculate only facts visible to this viewer, preserving confidential folders."""
    if not visible_goals(user, goal.organization).filter(pk=goal.pk).exists():
        raise PermissionDenied("Esta meta não está disponível para seu acesso.")
    if goal.metric == Goal.Metric.MANUAL:
        return goal.manual_value
    end = min(goal.ends_on, timezone.localdate())
    if goal.starts_on > end:
        return Decimal("0")
    matters = visible_matters(user, goal.organization)
    if goal.niche:
        matters = matters.filter(area__in=practice_area_values(goal.niche))
    if goal.metric == Goal.Metric.MATTERS:
        matters = matters.filter(created_at__date__range=(goal.starts_on, end))
        if goal.owner_id:
            matters = matters.filter(owner_id=goal.owner_id)
        return Decimal(matters.count())
    if goal.metric == Goal.Metric.TASKS:
        tasks = Task.objects.filter(organization=goal.organization, status=Task.Status.DONE)
        tasks = tasks.filter(matter_id__in=matters) if goal.niche else tasks.filter(Q(matter__isnull=True) | Q(matter_id__in=matters))
        if goal.owner_id:
            tasks = tasks.filter(owner_id=goal.owner_id)
        # A legacy task without a completion date is only counted if the audit trail proves one.
        completion = AuditEvent.objects.filter(
            organization=goal.organization, object_type="legal.task", object_id=Cast(OuterRef("pk"), CharField()), action="task.completed",
        ).order_by("-created_at").values("created_at")[:1]
        tasks = tasks.annotate(completion_date=Coalesce("completed_at", Subquery(completion)))
        return Decimal(tasks.filter(completion_date__date__range=(goal.starts_on, end)).count())
    payments = Payment.objects.filter(
        organization=goal.organization, entry__kind="income", date__range=(goal.starts_on, end),
    )
    payments = payments.filter(entry__matter_id__in=matters) if goal.niche else payments.filter(Q(entry__matter__isnull=True) | Q(entry__matter_id__in=matters))
    if goal.owner_id:
        # A reversal belongs to the person who recorded the original receipt,
        # even when another manager performs the reversal. Its own date still
        # determines the period in which the adjustment is recognized.
        payments = payments.filter(
            Q(reversal_of__isnull=True, created_by_id=goal.owner_id)
            | Q(reversal_of__isnull=False, reversal_of__created_by_id=goal.owner_id)
        )
    totals = payments.aggregate(received=Sum("amount", filter=Q(reversal_of__isnull=True)), reversed=Sum("amount", filter=Q(reversal_of__isnull=False)))
    return (totals["received"] or Decimal("0")) - (totals["reversed"] or Decimal("0"))


def goal_card(goal, user):
    value = goal_progress(goal, user)
    percent = max(0, min(100, int(value / goal.target * 100)))
    today = timezone.localdate()
    state = "Alcançada" if value >= goal.target else "Ainda não começou" if goal.starts_on > today else "Período encerrado" if goal.ends_on < today else "Em andamento"
    return {"goal": goal, "value": value, "percent": percent, "state": state, "is_money": goal.metric == Goal.Metric.REVENUE}


def dashboard_goals(user, organization, niche="", limit=4):
    today = timezone.localdate()
    goals = visible_goals(user, organization).filter(archived=False, starts_on__lte=today, ends_on__gte=today).select_related("organization", "owner")
    if niche:
        goals = goals.filter(niche=niche)
    return [goal_card(goal, user) for goal in goals[:limit]]


@transaction.atomic
def save_goal(*, actor, organization, data, goal_id=None):
    _authorize(actor, organization, data["metric"])
    goal = Goal.objects.select_for_update().get(pk=goal_id, organization=organization) if goal_id else Goal(organization=organization, created_by=actor)
    if goal.pk and data["metric"] != goal.metric:
        raise ValidationError("O indicador de uma meta existente deve ser preservado.")
    for key in ("title", "description", "metric", "target", "starts_on", "ends_on", "owner", "niche", "archived"):
        setattr(goal, key, data[key])
    if goal.niche and goal.niche not in organization.practice_areas:
        raise ValidationError("Escolha uma área de atuação configurada pela administração.")
    creating = goal.pk is None
    goal.save()
    audit(organization=organization, actor=actor, action="goal.created" if creating else "goal.updated", obj=goal,
          description=f"Indicador {goal.metric}; objetivo {goal.target}; período {goal.starts_on} a {goal.ends_on}; área {goal.niche or 'todas'}.")
    return goal


@transaction.atomic
def record_progress(*, actor, organization, goal_id, value, note):
    goal = Goal.objects.select_for_update().get(pk=goal_id, organization=organization)
    _authorize(actor, organization, goal.metric)
    if goal.metric != Goal.Metric.MANUAL or goal.archived:
        raise ValidationError("Apenas metas manuais ativas podem receber atualizações de progresso.")
    if goal.starts_on > timezone.localdate():
        raise ValidationError("Aguarde o início do período para registrar progresso.")
    try:
        value = Decimal(value)
        if not value.is_finite() or value < 0 or value != value.quantize(Decimal("0.01")):
            raise InvalidOperation
    except (TypeError, InvalidOperation, ValueError):
        raise ValidationError("Informe um valor não negativo com até duas casas decimais.") from None
    update = GoalUpdate.objects.create(organization=organization, goal=goal, previous_value=goal.manual_value, value=value, note=note.strip(), actor=actor)
    goal.manual_value = value
    goal.save(update_fields=["manual_value", "updated_at"])
    audit(organization=organization, actor=actor, action="goal.progress", obj=goal, description=f"Progresso: {update.previous_value} → {value}. Evidência: {update.note}")
    return goal
