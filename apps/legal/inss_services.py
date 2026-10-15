"""INSS & Previdia administrative demand tracking and synchronization services.

Tracks administrative benefits, requirements (exigências), decisions,
and safeguards against duplicate tasks/alerts when re-importing identical requirements.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AdministrativeDemand, Contact, Matter
from .services import audit


@transaction.atomic
def import_or_update_administrative_demand(
    *,
    organization,
    contact,
    matter,
    protocol_number,
    service_name,
    original_status,
    internal_status=None,
    demands_summary="",
    next_action="",
    assigned_to=None,
    is_manual=True,
):
    """Import or update an INSS demand idempotently. Never duplicates alerts for existing requirements."""
    protocol = protocol_number.strip()
    if not protocol:
        raise ValidationError("O número do protocolo é obrigatório.")

    demand = AdministrativeDemand.objects.filter(
        organization=organization,
        protocol_number=protocol,
    ).first()

    status_val = internal_status or (
        AdministrativeDemand.Status.REQUIREMENT if "exigência" in original_status.lower()
        else AdministrativeDemand.Status.REJECTED if "indeferido" in original_status.lower()
        else AdministrativeDemand.Status.CONCLUDED if ("concluído" in original_status.lower() or "deferido" in original_status.lower())
        else AdministrativeDemand.Status.PENDING
    )

    is_new = demand is None
    if is_new:
        demand = AdministrativeDemand.objects.create(
            organization=organization,
            contact=contact,
            matter=matter,
            protocol_number=protocol,
            service_name=service_name.strip(),
            source_agency="INSS",
            original_status=original_status.strip(),
            status=status_val,
            demands_summary=demands_summary.strip(),
            next_action=next_action.strip(),
            assigned_to=assigned_to,
            sync_status=AdministrativeDemand.SyncStatus.SUCCESS,
            last_sync_at=timezone.now(),
            is_manual_entry=is_manual,
        )
        audit(
            organization=organization,
            actor=assigned_to,
            action="admin_demand.created",
            obj=matter,
            description=f"Requerimento INSS cadastrado: {protocol} ({service_name}). Situação: {original_status}",
        )
    else:
        # Update existing record without generating duplicate events if unchanged
        changed = False
        if demand.original_status != original_status.strip():
            demand.original_status = original_status.strip()
            demand.status = status_val
            changed = True
        if demands_summary and demand.demands_summary != demands_summary.strip():
            demand.demands_summary = demands_summary.strip()
            changed = True
        if next_action and demand.next_action != next_action.strip():
            demand.next_action = next_action.strip()
            changed = True

        demand.last_sync_at = timezone.now()
        demand.sync_status = AdministrativeDemand.SyncStatus.SUCCESS
        demand.save()

        if changed:
            audit(
                organization=organization,
                actor=assigned_to,
                action="admin_demand.updated",
                obj=matter,
                description=f"Requerimento INSS {protocol} atualizado: {original_status}",
            )

    return demand, is_new


@transaction.atomic
def record_sync_failure(demand, failure_note):
    """Mark synchronization as pending update with visible alert; never claim 'no pending items'."""
    demand.sync_status = AdministrativeDemand.SyncStatus.PENDING_UPDATE
    demand.sync_notes = failure_note.strip()
    demand.save(update_fields=["sync_status", "sync_notes"])
    return demand
