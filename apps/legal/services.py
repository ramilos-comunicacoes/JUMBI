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
    FinanceEntry, Matter, Payment, Task, validate_document_file,
)


def _active_user(user):
    return bool(user and user.is_authenticated and user.is_active)


def visible_matters(user, organization):
    """A tenant role never implies permission to a confidential matter."""
    if getattr(organization, "status", "active") != "active" or not _active_user(user) or not Membership.objects.filter(
        organization=organization, user=user, is_active=True
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
    task.save(update_fields=["status", "completion_note"])
    audit(organization=task.organization, actor=actor, action="task.completed", obj=task,
          description=f"Evidência de conclusão: {evidence}")
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
