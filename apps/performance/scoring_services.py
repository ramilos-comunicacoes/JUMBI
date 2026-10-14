"""Scoring engine and leaderboard for team performance and office goals."""

from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Q, Count
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import ScoreEvent, ScoreRule
from apps.core.models import Membership, User


DEFAULT_RULES = {
    ScoreRule.EventType.CONTRACT_CLOSED: ("Contrato formalizado e validado", Decimal("50.00")),
    ScoreRule.EventType.COURT_FILING: ("Protocolo judicial ou administrativo com comprovante", Decimal("30.00")),
    ScoreRule.EventType.TASK_COMPLETED: ("Tarefa concluída com evidência", Decimal("10.00")),
    ScoreRule.EventType.CLIENT_CONTACT: ("Atendimento ao cliente concluído", Decimal("5.00")),
}


def get_or_create_default_rule(organization, event_type):
    """Ensure standard scoring rule exists for the office."""
    rule = ScoreRule.objects.filter(organization=organization, event_type=event_type).first()
    if not rule:
        title, pts = DEFAULT_RULES.get(event_type, ("Entrega de rotina", Decimal("10.00")))
        rule = ScoreRule.objects.create(
            organization=organization,
            event_type=event_type,
            title=title,
            points=pts,
            is_active=True,
        )
    return rule


@transaction.atomic
def record_score_event(*, organization, user, event_type, source_obj, description=""):
    """Credit points for an authorized deliverable with strict idempotency."""
    rule = get_or_create_default_rule(organization, event_type)
    if not rule.is_active:
        return None

    source_model = source_obj._meta.label_lower
    source_id = str(source_obj.pk)

    # Check if this exact deliverable was already scored
    existing = ScoreEvent.objects.filter(
        organization=organization,
        rule=rule,
        source_model=source_model,
        source_id=source_id,
        is_reversal=False,
    ).first()
    if existing:
        return existing

    event = ScoreEvent.objects.create(
        organization=organization,
        rule=rule,
        user=user,
        points=rule.points,
        source_model=source_model,
        source_id=source_id,
        description=description.strip(),
        is_reversal=False,
    )
    return event


@transaction.atomic
def reverse_score_event(*, score_event, actor, reason):
    """Record an explicit adjustment/reversal when a deliverable is cancelled or reopened."""
    if score_event.is_reversal:
        raise ValidationError("Não é permitido estornar um ajuste.")
    if hasattr(score_event, "reversed_by"):
        raise ValidationError("Este evento de pontuação já foi estornado.")

    reversal = ScoreEvent.objects.create(
        organization=score_event.organization,
        rule=score_event.rule,
        user=score_event.user,
        points=score_event.points,
        source_model=score_event.source_model,
        source_id=score_event.source_id,
        description=f"Estorno/ajuste por {actor.get_full_name() or actor.email}. Motivo: {reason.strip()}",
        is_reversal=True,
        reversal_of=score_event,
    )
    return reversal


def team_ranking(organization, period_days=30):
    """Calculate net leaderboard points per collaborator over the given period."""
    since = timezone.now() - timezone.timedelta(days=period_days) if period_days else None

    events = ScoreEvent.objects.filter(organization=organization)
    if since:
        events = events.filter(created_at__gte=since)

    memberships = Membership.objects.filter(
        organization=organization,
        is_active=True,
        user__is_active=True,
    ).exclude(role="client").select_related("user")

    user_map = {m.user_id: m.user for m in memberships}

    leaderboard = []
    for user_id, user in user_map.items():
        user_events = events.filter(user_id=user_id)
        earned = user_events.filter(is_reversal=False).aggregate(total=Sum("points"))["total"] or Decimal("0.00")
        reversed_pts = user_events.filter(is_reversal=True).aggregate(total=Sum("points"))["total"] or Decimal("0.00")
        net = earned - reversed_pts
        deliveries = user_events.filter(is_reversal=False).count()

        leaderboard.append({
            "user": user,
            "name": user.get_full_name() or user.email,
            "points": net,
            "deliveries": deliveries,
        })

    leaderboard.sort(key=lambda x: (x["points"], x["deliveries"]), reverse=True)

    # Assign ranks handling ties
    rank = 1
    for i, item in enumerate(leaderboard):
        if i > 0 and (item["points"] == leaderboard[i - 1]["points"] and item["deliveries"] == leaderboard[i - 1]["deliveries"]):
            item["rank"] = leaderboard[i - 1]["rank"]
        else:
            item["rank"] = rank
        rank += 1

    return leaderboard
