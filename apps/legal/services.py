"""Explicit, authorized and auditable legal-domain transitions."""

from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.core.models import Membership
from .models import (
    AuditEvent, Deadline, DeadlineRevision, Document, DocumentVersion,
    FinanceEntry, Matter, Payment, Task, allow_immutable_delete, validate_document_file,
)


def _active_user(user):
    return bool(user and user.is_authenticated and user.is_active)


def visible_matters(user, organization):
    """A tenant role never implies permission to a confidential matter."""
    if getattr(organization, "status", "active") != "active" or not _active_user(user) or not Membership.objects.filter(
        organization=organization, user=user, is_active=True, role__in=['owner', 'manager', 'operator', 'viewer']
    ).exists():
        return Matter.objects.none()
    return Matter.objects.filter(organization=organization).filter(
        Q(confidential=False) | Q(owner=user) | Q(members=user)
    ).distinct()


def can_write(user, organization):
    return getattr(organization, "status", "active") == "active" and _active_user(user) and Membership.objects.filter(
        organization=organization, user=user, is_active=True,
        role__in=["owner", "manager", "operator"],
    ).exists()


def can_manage_finance(user, organization):
    return getattr(organization, "status", "active") == "active" and _active_user(user) and Membership.objects.filter(
        organization=organization, user=user, is_active=True, role__in=["owner", "manager"],
    ).exists()


def _authorize_write(*, actor, obj):
    from apps.billing.services import require_access
    require_access(obj.organization, advanced=isinstance(obj, (FinanceEntry, Payment)))
    if not can_write(actor, obj.organization):
        raise PermissionDenied("Você não tem permissão para alterar este escritório.")
    if isinstance(obj, (FinanceEntry, Payment)) and not can_manage_finance(actor, obj.organization):
        raise PermissionDenied("Somente a direção e a gestão podem registrar movimentações financeiras.")
    matter_id = obj.pk if isinstance(obj, Matter) else getattr(obj, "matter_id", None)
    if isinstance(obj, Payment):
        matter_id = obj.entry.matter_id
    if isinstance(obj, DocumentVersion):
        matter_id = obj.document.matter_id
    if matter_id and not visible_matters(actor, obj.organization).filter(pk=matter_id).exists():
        raise PermissionDenied("Você não tem acesso à pasta vinculada.")


def audit(*, organization, actor, action, obj=None, description=""):
    if obj is not None and getattr(obj, "organization_id", organization.pk) != organization.pk:
        raise ValidationError("O registro de auditoria deve pertencer ao mesmo escritório.")
    return AuditEvent.objects.create(
        organization=organization,
        actor=actor,
        action=action,
        object_type=obj._meta.label_lower if obj is not None else "core.organization",
        object_id=str(obj.pk if obj is not None else organization.pk),
        description=description,
    )


def _required_text(value, label):
    value = (value or "").strip()
    if not value:
        raise ValidationError(f"Informe {label}.")
    return value


def _amount(value):
    # Floats already lost decimal precision before reaching the service.
    if isinstance(value, (float, bool)):
        raise ValidationError("Informe um valor decimal com até duas casas.")
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Informe um valor positivo com até duas casas decimais.")
    return amount.quantize(Decimal("0.01"))


@transaction.atomic
def complete_task(*, task, actor, evidence):
    task = Task.objects.select_for_update().get(pk=task.pk, organization_id=task.organization_id)
    _authorize_write(actor=actor, obj=task)
    evidence = _required_text(evidence, "a evidência de conclusão da tarefa")
    if task.status == Task.Status.DONE:
        raise ValidationError("A tarefa já está concluída.")
    task.status = Task.Status.DONE
    task.completion_note = evidence
    task.completed_at = timezone.now()
    task.save(update_fields=["status", "completion_note", "completed_at"])
    audit(organization=task.organization, actor=actor, action="task.completed", obj=task,
          description=f"Evidência de conclusão: {evidence}")
    return task


@transaction.atomic
def move_task(*, task, actor, destination, expected_status, note=""):
    """Move a Kanban card without silently overwriting another person's move."""
    task = Task.objects.select_for_update().get(pk=task.pk, organization_id=task.organization_id)
    _authorize_write(actor=actor, obj=task)
    if destination not in Task.Status.values or expected_status not in Task.Status.values:
        raise ValidationError("Escolha uma coluna válida.")
    if task.status != expected_status:
        raise ValidationError("Esta tarefa foi alterada por outra pessoa. Atualize o quadro antes de movê-la.")
    if task.status == destination:
        return task
    previous = task.status
    if destination == Task.Status.CANCELLED:
        note = _required_text(note, "o motivo do cancelamento")
    elif previous == Task.Status.CANCELLED:
        note = _required_text(note, "o motivo da reativação")
    elif previous == Task.Status.DONE:
        note = _required_text(note, "o motivo da reabertura")
    if destination == Task.Status.DONE:
        return complete_task(task=task, actor=actor, evidence=note)
    task.status = destination
    task.completed_at = None
    # Evidence of earlier completions remains in the immutable audit trail.
    task.completion_note = ""
    task.save(update_fields=["status", "completed_at", "completion_note"])
    action = "task.cancelled" if destination == Task.Status.CANCELLED else "task.reopen" if previous in {Task.Status.DONE, Task.Status.CANCELLED} else "task.moved"
    audit(organization=task.organization, actor=actor, action=action, obj=task,
          description=f"{dict(Task.Status.choices)[previous]} → {task.get_status_display()}. {note.strip()}")
    return task


def _save_deadline_transition(deadline, fields):
    deadline._allow_transition = True
    try:
        deadline.save(update_fields=fields)
    finally:
        del deadline._allow_transition


@transaction.atomic
def confirm_deadline(*, deadline, actor):
    deadline = Deadline.objects.select_for_update().get(pk=deadline.pk, organization_id=deadline.organization_id)
    _authorize_write(actor=actor, obj=deadline)
    if deadline.status != Deadline.Status.PENDING:
        raise ValidationError("Somente prazos pendentes podem ser conferidos.")
    deadline.status = Deadline.Status.CONFIRMED
    deadline.confirmed_by = actor
    deadline.confirmed_at = timezone.now()
    _save_deadline_transition(deadline, ["status", "confirmed_by", "confirmed_at"])
    audit(organization=deadline.organization, actor=actor, action="deadline.confirmed", obj=deadline,
          description=f"Prazo conferido para {deadline.due_date.isoformat()}.")
    return deadline


@transaction.atomic
def revise_deadline(*, deadline, actor, due_date, reason):
    deadline = Deadline.objects.select_for_update().get(pk=deadline.pk, organization_id=deadline.organization_id)
    _authorize_write(actor=actor, obj=deadline)
    reason = _required_text(reason, "o motivo da revisão")
    due_date = Deadline._meta.get_field("due_date").clean(due_date, deadline)
    if deadline.status == Deadline.Status.FULFILLED:
        raise ValidationError("Prazos cumpridos preservam sua data. Registre uma nova obrigação quando necessário.")
    if due_date == deadline.due_date:
        raise ValidationError("O novo vencimento deve ser diferente do anterior.")
    DeadlineRevision.objects.create(
        organization=deadline.organization, deadline=deadline,
        previous_date=deadline.due_date, new_date=due_date, reason=reason, actor=actor,
    )
    previous_date = deadline.due_date
    deadline.due_date = due_date
    # A changed legal date always returns to explicit human review.
    deadline.status = Deadline.Status.PENDING
    deadline.confirmed_by = None
    deadline.confirmed_at = None
    deadline.evidence = ""
    _save_deadline_transition(deadline, ["due_date", "status", "confirmed_by", "confirmed_at", "evidence"])
    audit(organization=deadline.organization, actor=actor, action="deadline.revised", obj=deadline,
          description=f"Vencimento alterado de {previous_date.isoformat()} para {due_date.isoformat()}; nova conferência necessária.")
    return deadline


@transaction.atomic
def fulfill_deadline(*, deadline, actor, evidence):
    deadline = Deadline.objects.select_for_update().get(pk=deadline.pk, organization_id=deadline.organization_id)
    _authorize_write(actor=actor, obj=deadline)
    evidence = _required_text(evidence, "a evidência de cumprimento da obrigação")
    if deadline.status != Deadline.Status.CONFIRMED:
        raise ValidationError("Confira o prazo antes de registrar seu cumprimento.")
    deadline.status = Deadline.Status.FULFILLED
    deadline.evidence = evidence
    _save_deadline_transition(deadline, ["status", "evidence"])
    audit(organization=deadline.organization, actor=actor, action="deadline.fulfilled", obj=deadline,
          description="Cumprimento registrado com evidência após conferência humana.")
    return deadline


@transaction.atomic
def record_payment(*, entry, actor, amount, date=None, note="", operation_key=None):
    # All movements of one entry serialize on the same row, including reversals.
    entry = FinanceEntry.objects.select_for_update().get(pk=entry.pk, organization_id=entry.organization_id)
    _authorize_write(actor=actor, obj=entry)
    amount = _amount(amount)
    date = Payment._meta.get_field("date").clean(date or timezone.localdate(), None)
    try:
        operation_key = UUID(str(operation_key)) if operation_key is not None else uuid4()
    except (TypeError, ValueError, AttributeError):
        raise ValidationError("Identificação de operação inválida. Atualize a página e tente novamente.") from None

    def existing_operation():
        existing = Payment.objects.filter(operation_key=operation_key).first()
        if existing is None:
            return None
        if (
            existing.entry_id != entry.pk
            or existing.organization_id != entry.organization_id
            or existing.created_by_id != actor.pk
            or existing.reversal_of_id is not None
            or existing.amount != amount
            or existing.date != date
            or existing.note != note
        ):
            raise ValidationError("Esta identificação de operação já foi utilizada com outros dados. Atualize a página para registrar uma nova baixa.")
        return existing

    # Check before the balance: a retry remains successful after the original
    # payment exhausted the balance, or after that payment was later reversed.
    previous_payment = existing_operation()
    if previous_payment is not None:
        return previous_payment
    if amount > entry.balance:
        raise ValidationError("A baixa não pode exceder o saldo do lançamento.")
    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                organization=entry.organization, entry=entry, created_by=actor,
                amount=amount, date=date, note=note, operation_key=operation_key,
            )
    except IntegrityError:
        # Distinct entry locks may race for one key. The unique constraint is
        # authoritative; recover only that collision, not another database error.
        previous_payment = existing_operation()
        if previous_payment is not None:
            return previous_payment
        raise
    audit(organization=entry.organization, actor=actor, action="payment.recorded", obj=payment,
          description=f"Baixa de {amount:.2f}; saldo do lançamento {entry.balance:.2f}.")
    return payment


@transaction.atomic
def reverse_payment(*, payment, actor, note, date=None):
    entry = FinanceEntry.objects.select_for_update().get(
        pk=payment.entry_id, organization_id=payment.organization_id
    )
    _authorize_write(actor=actor, obj=entry)
    payment = Payment.objects.select_for_update().get(pk=payment.pk, entry=entry)
    note = _required_text(note, "o motivo do estorno")
    if payment.reversal_of_id:
        raise ValidationError("Não é permitido estornar um estorno. Registre uma nova baixa.")
    if Payment.objects.filter(reversal_of=payment).exists():
        raise ValidationError("Esta baixa já foi estornada.")
    reversal = Payment.objects.create(
        organization=entry.organization, entry=entry, created_by=actor,
        amount=payment.amount, date=date or timezone.localdate(), note=note, reversal_of=payment,
    )
    audit(organization=entry.organization, actor=actor, action="payment.reversed", obj=reversal,
          description=f"Baixa {payment.pk} estornada em {payment.amount:.2f}; saldo do lançamento {entry.balance:.2f}.")
    return reversal


def add_document_version(*, document, actor, file):
    validate_document_file(file)
    version = None
    try:
        with transaction.atomic():
            from apps.billing.services import check_capacity
            check_capacity(document.organization, "versions")
            document = Document.objects.select_for_update().get(
                pk=document.pk, organization_id=document.organization_id
            )
            _authorize_write(actor=actor, obj=document)
            number = (document.versions.aggregate(maximum=Max("number"))["maximum"] or 0) + 1
            version = DocumentVersion(
                organization=document.organization, document=document, number=number,
                file=file, original_name=file.name, uploaded_by=actor,
            )
            version.save()
            audit(organization=document.organization, actor=actor, action="document.version_added", obj=document,
                  description=f"Versão {number} preservada; SHA-256 {version.checksum}.")
        return version
    except Exception:
        # File storage cannot roll back with the database. Remove only the new
        # random-path file from this failed write, never an earlier version.
        if version is not None and version.file and version.file._committed:
            version.file.storage.delete(version.file.name)
        raise


def ensure_client_matter(*, contact, actor=None, area=None, title=None):
    """Ensures a Contact has an active Matter (Pasta jurídica).

    Creates a default active matter if none exists, linking it to the client.
    """
    from apps.core.niches import PRACTICE_AREA_LABELS
    from apps.core.models import Membership
    from apps.billing.services import check_capacity

    if not contact or not getattr(contact, "pk", None):
        return None

    existing = Matter.objects.filter(organization=contact.organization, client=contact).first()
    if existing:
        return existing

    org = contact.organization
    owner = actor if (actor and getattr(actor, "is_authenticated", False)) else None
    if not owner:
        owner_member = Membership.objects.filter(
            organization=org, role__in=["owner", "manager"], is_active=True, user__is_active=True
        ).select_related("user").first()
        owner = owner_member.user if owner_member else None

    if not owner:
        member = Membership.objects.filter(
            organization=org, is_active=True, user__is_active=True
        ).select_related("user").first()
        owner = member.user if member else None

    if not owner:
        return None

    matter_area = area or ""
    if not matter_area and getattr(org, "practice_areas", None):
        primary_code = org.practice_areas[0]
        matter_area = PRACTICE_AREA_LABELS.get(primary_code, primary_code)
    if not matter_area:
        matter_area = "Geral"

    matter_title = title or f"Pasta Geral · {contact.name}"

    matter = Matter(
        organization=org,
        client=contact,
        title=matter_title[:240],
        owner=owner,
        nature=Matter.Nature.ADVISORY,
        area=matter_area,
        status=Matter.Status.ACTIVE,
        description=f"Pasta jurídica criada automaticamente para {contact.name}.",
        confidential=False,
    )
    check_capacity(org, "matters", instance=matter)
    matter.full_clean()
    matter.save()

    audit(
        organization=org,
        actor=owner,
        action="record.created",
        obj=matter,
        description=f"Pasta jurídica '{matter.title}' criada automaticamente para o cliente {contact.name}.",
    )
    return matter


@transaction.atomic
def delete_contact_and_matters(*, contact, actor=None):
    """Safely cascades deletion of a contact and all their linked matters and records."""
    org = contact.organization
    with allow_immutable_delete():
        matters = Matter.objects.filter(organization=org, client=contact)
        matter_ids = list(matters.values_list("pk", flat=True))

        # 1. Tasks & worklog comments
        tasks = Task.objects.filter(organization=org, matter_id__in=matter_ids)
        try:
            from apps.worklog.models import TaskComment
            TaskComment.objects.filter(task__in=tasks).delete()
        except Exception:
            pass
        tasks.delete()

        # 2. Deadlines and revisions
        deadlines = Deadline.objects.filter(organization=org, matter_id__in=matter_ids)
        DeadlineRevision.objects.filter(organization=org, deadline__in=deadlines).delete()
        deadlines.delete()

        # 3. Documents, versions, portal reviews and publications
        docs = Document.objects.filter(organization=org, matter_id__in=matter_ids)
        versions = DocumentVersion.objects.filter(organization=org, document__in=docs)
        try:
            from apps.portal.models import PublicationMessage, Publication, DocumentDecision, DocumentReview
            reviews = DocumentReview.objects.filter(version__in=versions)
            PublicationMessage.objects.filter(publication__review__in=reviews).delete()
            Publication.objects.filter(review__in=reviews).delete()
            DocumentDecision.objects.filter(review__in=reviews).delete()
            reviews.delete()
        except Exception:
            pass

        for v in versions:
            try:
                if v.file:
                    v.file.delete(save=False)
            except Exception:
                pass
        versions.delete()
        docs.delete()

        # 4. Finance, payments and receipts
        try:
            from .models import PaymentReceipt
            PaymentReceipt.objects.filter(organization=org, matter_id__in=matter_ids).delete()
        except Exception:
            pass
        entries = FinanceEntry.objects.filter(organization=org, matter_id__in=matter_ids)
        Payment.objects.filter(organization=org, entry__in=entries).delete()
        entries.delete()

        # 5. Routines
        try:
            from apps.routines.models import RoutineCheckItem, RoutineComment, RoutineApplication
            RoutineCheckItem.objects.filter(matter_id__in=matter_ids).delete()
            RoutineComment.objects.filter(matter_id__in=matter_ids).delete()
            RoutineApplication.objects.filter(matter_id__in=matter_ids).delete()
        except Exception:
            pass

        # 6. Court Cases, Appointments, Demands, Contacts and Opportunities
        from .models import CourtCase, Appointment, AdministrativeDemand, ClientContact, Opportunity
        CourtCase.objects.filter(organization=org, matter_id__in=matter_ids).delete()
        Appointment.objects.filter(organization=org, matter_id__in=matter_ids).delete()
        AdministrativeDemand.objects.filter(organization=org).filter(Q(matter_id__in=matter_ids) | Q(contact=contact)).delete()
        ClientContact.objects.filter(organization=org).filter(Q(matter_id__in=matter_ids) | Q(contact=contact)).delete()
        Opportunity.objects.filter(organization=org, contact=contact).delete()

        # 7. Contracts and Fee Plans
        try:
            from apps.contracts.models import ContractRevision, Contract
            contracts = Contract.objects.filter(organization=org, client=contact)
            ContractRevision.objects.filter(contract__in=contracts).delete()
            contracts.delete()
        except Exception:
            pass

        try:
            from apps.fees.models import FeePlan
            FeePlan.objects.filter(organization=org, client=contact).delete()
        except Exception:
            pass

        # 8. Portal client access
        try:
            from apps.portal.models import PublicationMessage, Publication, ClientAccess
            accesses = ClientAccess.objects.filter(contact=contact)
            PublicationMessage.objects.filter(publication__access__in=accesses).delete()
            Publication.objects.filter(access__in=accesses).delete()
            accesses.delete()
        except Exception:
            pass

        # 9. Communications (DJEN, PJe)
        try:
            from .models import DjenCommunication
            DjenCommunication.objects.filter(organization=org, matter_id__in=matter_ids).delete()
        except Exception:
            pass
        try:
            from apps.integrations.models import CourtCommunication
            CourtCommunication.objects.filter(organization=org, matter_id__in=matter_ids).delete()
        except Exception:
            pass

        # 10. Birthday notifications
        try:
            from apps.notifications.models import BirthdayNotification
            BirthdayNotification.objects.filter(contact=contact).delete()
        except Exception:
            pass

        # 11. Delete matters
        matters_count = len(matter_ids)
        matters.delete()

        # 12. Delete contact
        contact_name = contact.name
        contact.delete()

        # 13. Audit
        audit(
            organization=org,
            actor=actor,
            action="contact.deleted",
            description=f"Cliente '{contact_name}' e {matters_count} pasta(s) vinculada(s) foram excluídos com sucesso.",
        )
    return matters_count


@transaction.atomic
def reset_organization_operational_data(*, organization, actor=None):
    """Safely resets all operational data for an organization, preserving accounts, team and subscription."""
    org = organization
    with allow_immutable_delete():
        # 1. Worklog comments & tasks
        try:
            from apps.worklog.models import TaskComment
            TaskComment.objects.filter(task__organization=org).delete()
        except Exception:
            pass
        Task.objects.filter(organization=org).delete()

        # 2. Deadlines and revisions
        DeadlineRevision.objects.filter(organization=org).delete()
        Deadline.objects.filter(organization=org).delete()

        # 3. Documents, versions, portal reviews & publications
        try:
            from apps.portal.models import PublicationMessage, Publication, DocumentDecision, DocumentReview, ClientAccess
            PublicationMessage.objects.filter(publication__review__version__document__organization=org).delete()
            Publication.objects.filter(review__version__document__organization=org).delete()
            DocumentDecision.objects.filter(review__version__document__organization=org).delete()
            DocumentReview.objects.filter(version__document__organization=org).delete()
            PublicationMessage.objects.filter(publication__access__contact__organization=org).delete()
            Publication.objects.filter(access__contact__organization=org).delete()
            ClientAccess.objects.filter(contact__organization=org).delete()
        except Exception:
            pass

        for v in DocumentVersion.objects.filter(organization=org):
            try:
                if v.file:
                    v.file.delete(save=False)
            except Exception:
                pass
        DocumentVersion.objects.filter(organization=org).delete()
        Document.objects.filter(organization=org).delete()

        # 4. Finance, payments, receipts, fee plans
        try:
            from .models import PaymentReceipt
            PaymentReceipt.objects.filter(organization=org).delete()
        except Exception:
            pass
        Payment.objects.filter(organization=org).delete()
        FinanceEntry.objects.filter(organization=org).delete()
        try:
            from apps.fees.models import FeePlan
            FeePlan.objects.filter(organization=org).delete()
        except Exception:
            pass

        # 5. Routines
        try:
            from apps.routines.models import RoutineCheckItem, RoutineComment, RoutineApplication
            RoutineCheckItem.objects.filter(matter__organization=org).delete()
            RoutineComment.objects.filter(matter__organization=org).delete()
            RoutineApplication.objects.filter(matter__organization=org).delete()
        except Exception:
            pass

        # 6. Court Cases, Appointments, Demands, Contacts and Opportunities
        from .models import CourtCase, Appointment, AdministrativeDemand, ClientContact, Opportunity, Contact
        CourtCase.objects.filter(organization=org).delete()
        Appointment.objects.filter(organization=org).delete()
        AdministrativeDemand.objects.filter(organization=org).delete()
        ClientContact.objects.filter(organization=org).delete()
        Opportunity.objects.filter(organization=org).delete()

        # 7. Contracts
        try:
            from apps.contracts.models import ContractRevision, Contract
            ContractRevision.objects.filter(contract__organization=org).delete()
            Contract.objects.filter(organization=org).delete()
        except Exception:
            pass

        # 8. Communications (DJEN, PJe)
        try:
            from .models import DjenCommunication, DjenSearchRun
            DjenCommunication.objects.filter(organization=org).delete()
            DjenSearchRun.objects.filter(organization=org).delete()
        except Exception:
            pass
        try:
            from apps.integrations.models import CourtCommunication
            CourtCommunication.objects.filter(organization=org).delete()
        except Exception:
            pass

        # 9. Performance goals
        try:
            from apps.performance.models import GoalUpdate, Goal, ScoreEvent
            GoalUpdate.objects.filter(goal__organization=org).delete()
            ScoreEvent.objects.filter(organization=org).delete()
            Goal.objects.filter(organization=org).delete()
        except Exception:
            pass

        # 10. Intake batches
        try:
            from apps.intake.models import ImportBatch
            ImportBatch.objects.filter(organization=org).delete()
        except Exception:
            pass

        # 11. Notifications
        try:
            from apps.notifications.models import Notification, BirthdayNotification
            BirthdayNotification.objects.filter(contact__organization=org).delete()
            Notification.objects.filter(recipient__memberships__organization=org).delete()
        except Exception:
            pass

        # 12. Matters and Contacts
        Matter.objects.filter(organization=org).delete()
        Contact.objects.filter(organization=org).delete()

        # 13. Audit trail (clean operational events, record reset event)
        AuditEvent.objects.filter(organization=org).delete()
        audit(
            organization=org,
            actor=actor,
            action="workspace.reset",
            description="O sistema do escritório foi resetado pelo administrador. Todos os dados operacionais foram limpos.",
        )
        from apps.core.models import AuditLog
        AuditLog.objects.create(
            organization=org,
            actor=actor,
            action="organization.reset",
            metadata={"actor": str(actor), "reset_at": timezone.now().isoformat()},
        )


