"""Triage and workflow automation for court communications.

Matches communications against matters and cases, generates deadlines
with urgency tracking, and creates operational tasks.
"""
from datetime import timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.legal.models import CourtCase as Case, Deadline, Matter, Task
from apps.legal.services import audit
from .models import CommunicationReview, CourtCommunication


def list_triage_queue(organization, status="PENDING_REVIEW", court=None, search=None):
    """Retrieve filtered court communications for triage inbox."""
    status_map = {
        "pending": CourtCommunication.ReviewStatus.PENDING_REVIEW,
        "confirmed": CourtCommunication.ReviewStatus.MATCH_CONFIRMED,
        "dismissed": CourtCommunication.ReviewStatus.NOT_RELEVANT,
        "needs_info": CourtCommunication.ReviewStatus.NEEDS_INFORMATION,
    }
    normalized_status = status_map.get(status, status)
    qs = CourtCommunication.objects.filter(
        organization=organization
    ).select_related("matter", "court_case", "deadline")

    if normalized_status:
        qs = qs.filter(review_status=normalized_status)
    if court:
        qs = qs.filter(Q(tribunal__iexact=court) | Q(body_or_court__icontains=court))
    if search:
        qs = qs.filter(
            Q(case_number__icontains=search) |
            Q(content_text__icontains=search) |
            Q(recipient_name__icontains=search) |
            Q(tribunal__icontains=search)
        )
    return qs.order_by("-available_date", "-created_at")


@transaction.atomic
def confirm_communication(
    *,
    communication: CourtCommunication,
    actor,
    matter: Matter = None,
    court_case: Case = None,
    create_deadline: bool = True,
    deadline_days: int = 15,
    task_title: str = None,
    assigned_to=None,
    notes: str = ""
):
    """Confirm a judicial communication, link to case/matter, and generate deadline & task."""
    comm = CourtCommunication.objects.select_for_update().get(pk=communication.pk)
    org = comm.organization

    # Link matter or attempt auto-resolution
    if not matter and comm.matter:
        matter = comm.matter
    elif not matter and comm.case_number:
        existing_case = Case.objects.filter(organization=org, number=comm.case_number).first()
        if existing_case:
            court_case = existing_case
            matter = existing_case.matter

    if court_case and not matter:
        matter = court_case.matter
    elif matter and not court_case and comm.case_number:
        court_case = Case.objects.filter(organization=org, matter=matter, number=comm.case_number).first()

    comm.matter = matter
    comm.court_case = court_case
    comm.review_status = CourtCommunication.ReviewStatus.MATCH_CONFIRMED
    comm.deadline_status = "CONFIRMADO"
    comm.reviewed_by = actor
    comm.reviewed_at = timezone.now()

    deadline_obj = None
    task_obj = None

    today = timezone.localdate()
    due_date = today + timedelta(days=max(1, deadline_days))

    # Determine responsible user
    owner = assigned_to or (matter.owner if matter else actor)

    if create_deadline:
        deadline_title = f"Prazo judicial · Comunicação {comm.external_id}"
        if comm.case_number:
            deadline_title = f"Prazo · Proc. {comm.case_number}"

        description = f"Origem: {comm.court_name}\n"
        if comm.communication_type:
            description += f"Tipo: {comm.communication_type}\n"
        if notes:
            description += f"Observações: {notes}\n"
        description += f"\nTrecho:\n{comm.full_content[:500]}..."

        deadline_obj = Deadline.objects.create(
            organization=org,
            matter=matter,
            title=deadline_title,
            due_date=due_date,
            kind=Deadline.Kind.COURT,
            status=Deadline.Status.PENDING,
            owner=owner,
            source=description,
        )
        comm.deadline = deadline_obj

    if task_title or create_deadline:
        t_title = task_title or f"Cumprir providência · Comunicação {comm.external_id}"
        task_obj = Task.objects.create(
            organization=org,
            matter=matter,
            title=t_title,
            description=f"Providência gerada a partir da triagem de comunicação judicial ({comm.court_name}).\nPrazo fatal estimado: {due_date.strftime('%d/%m/%Y')}",
            owner=owner,
            due_date=due_date - timedelta(days=2) if deadline_days > 3 else due_date,
            status=Task.Status.TODO,
            priority=Task.Priority.URGENT if deadline_days <= 5 else Task.Priority.HIGH,
            deadline=deadline_obj,
        )

    comm.save()

    # Record review audit
    review = CommunicationReview.objects.create(
        organization=org,
        communication=comm,
        reviewer=actor,
        decision=CourtCommunication.ReviewStatus.MATCH_CONFIRMED,
        case=matter,
        reason=notes or "Vínculo confirmado na triagem",
        proposed_actions=[{"task": t_title}] if task_obj else [],
    )

    audit(
        organization=org,
        actor=actor,
        action="integrations.communication_confirmed",
        obj=comm,
        description=f"Comunicação {comm.external_id} confirmada. Prazo: {due_date}. Providência atribuída a {owner.email}."
    )

    return comm, review


@transaction.atomic
def dismiss_communication(*, communication: CourtCommunication, actor, reason: str):
    """Dismiss a communication with reason recorded."""
    if not reason.strip():
        raise ValidationError("Informe o motivo do descarte da publicação.")

    comm = CourtCommunication.objects.select_for_update().get(pk=communication.pk)
    comm.review_status = CourtCommunication.ReviewStatus.NOT_RELEVANT
    comm.deadline_status = "DESCARTADO"
    comm.reviewed_by = actor
    comm.reviewed_at = timezone.now()
    comm.save(update_fields=["review_status", "deadline_status", "reviewed_by", "reviewed_at"])

    review = CommunicationReview.objects.create(
        organization=comm.organization,
        communication=comm,
        reviewer=actor,
        decision=CourtCommunication.ReviewStatus.NOT_RELEVANT,
        reason=reason.strip(),
    )

    audit(
        organization=comm.organization,
        actor=actor,
        action="integrations.communication_dismissed",
        obj=comm,
        description=f"Comunicação {comm.external_id} descartada. Motivo: {reason.strip()}"
    )

    return comm, review
