import calendar
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum

from apps.billing.services import has_advanced, require_access
from apps.core.models import Organization
from apps.legal.models import Contact, FinanceEntry, Matter
from apps.legal.services import audit, can_manage_finance, visible_matters
from .models import FeeInstallment, FeePlan


MAX_AMOUNT = Decimal("999999999999.99")


def build_schedule(*, kind, amount, periods, first_due_date):
    if kind not in FeePlan.Kind.values:
        raise ValidationError("Escolha uma modalidade válida.")
    if isinstance(amount, (float, bool)):
        raise ValidationError("Informe o valor decimal com até duas casas.")
    try:
        amount = Decimal(amount)
        if not amount.is_finite() or amount <= 0 or amount > MAX_AMOUNT or amount != amount.quantize(Decimal("0.01")):
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Informe um valor positivo com até duas casas decimais.") from None
    if type(periods) is not int or not 1 <= periods <= 36:
        raise ValidationError("Escolha entre 1 e 36 meses.")
    if type(first_due_date) is not date:
        raise ValidationError("Informe a data do primeiro vencimento.")
    total = amount * periods if kind == FeePlan.Kind.MONTHLY else amount
    if total > MAX_AMOUNT:
        raise ValidationError("O total do cronograma excede o limite permitido.")
    if kind == FeePlan.Kind.INSTALLMENTS and amount * 100 < periods:
        raise ValidationError("Cada parcela precisa ter ao menos R$ 0,01.")
    base_cents, remainder = divmod(int(amount * 100), periods)
    month_end = first_due_date.day == calendar.monthrange(first_due_date.year, first_due_date.month)[1]
    schedule = []
    for offset in range(periods):
        year, month = divmod(first_due_date.year * 12 + first_due_date.month - 1 + offset, 12)
        if year > 9999:
            raise ValidationError("O cronograma ultrapassa o limite de datas.")
        month += 1
        last_day = calendar.monthrange(year, month)[1]
        due = date(year, month, last_day if month_end else min(first_due_date.day, last_day))
        installment = amount if kind == FeePlan.Kind.MONTHLY else Decimal(base_cents + (1 if offset < remainder else 0)) / 100
        schedule.append({"number": offset + 1, "due_date": due, "amount": installment.quantize(Decimal("0.01"))})
    return schedule


def visible_plans(actor, organization, *, for_export=False):
    if not can_manage_finance(actor, organization) or (not for_export and not has_advanced(organization)):
        return FeePlan.objects.none()
    return FeePlan.objects.filter(organization=organization, matter__in=visible_matters(actor, organization))


def visible_installments(actor, organization, *, for_export=False):
    return FeeInstallment.objects.filter(organization=organization, plan__in=visible_plans(actor, organization, for_export=for_export))


@transaction.atomic
def create_plan(*, organization, actor, matter, client, title, kind, amount, periods, first_due_date, operation_key, notes=""):
    # One office lock serializes duplicate requests before any ledger is written.
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    require_access(organization, advanced=True)
    if not can_manage_finance(actor, organization):
        raise PermissionDenied("Somente a direção e a gestão podem cadastrar honorários.")
    if not matter or not visible_matters(actor, organization).filter(pk=matter.pk).exists():
        raise PermissionDenied("Você não tem acesso à pasta selecionada.")
    matter = Matter.objects.select_for_update().get(pk=matter.pk, organization=organization)
    if not client or not Contact.objects.filter(pk=client.pk, organization=organization).exists():
        raise ValidationError("Selecione um cliente deste escritório.")
    client = Contact.objects.get(pk=client.pk, organization=organization)
    if matter.client_id and matter.client_id != client.pk:
        raise ValidationError("O cliente precisa corresponder ao cadastro da pasta.")
    title = (title or "").strip()
    notes = (notes or "").strip()
    if not title or len(title) > 180 or len(notes) > 3000:
        raise ValidationError("Informe uma descrição de até 180 caracteres e condições de até 3.000 caracteres.")
    try:
        operation_key = UUID(str(operation_key))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError("Identificação inválida. Abra um novo cadastro.") from None
    schedule = build_schedule(kind=kind, amount=amount, periods=periods, first_due_date=first_due_date)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    fingerprint = hashlib.sha256(json.dumps({"actor": actor.pk, "matter": matter.pk, "client": client.pk, "title": title, "kind": kind, "amount": str(amount), "periods": periods, "first_due_date": first_due_date.isoformat(), "notes": notes}, sort_keys=True).encode()).hexdigest()
    existing = FeePlan.objects.filter(organization=organization, operation_key=operation_key).first()
    if existing:
        if existing.request_hash != fingerprint:
            raise ValidationError("Esta solicitação já foi usada com outros dados. Abra um novo cadastro.")
        return existing
    plan = FeePlan.objects.create(organization=organization, created_by=actor, matter=matter, client=client, title=title, kind=kind, amount=amount, total_amount=sum(row["amount"] for row in schedule), periods=periods, first_due_date=first_due_date, operation_key=operation_key, request_hash=fingerprint, notes=notes)
    for row in schedule:
        entry = FinanceEntry.objects.create(organization=organization, matter=matter, description=f"{title} · {row['number']}/{periods}", kind=FinanceEntry.Kind.INCOME, amount=row["amount"], due_date=row["due_date"])
        FeeInstallment.objects.create(organization=organization, plan=plan, entry=entry, **row)
    audit(organization=organization, actor=actor, action="fees.plan_created", obj=plan, description=f"{plan.get_kind_display()}: {periods} parcelas; total previsto R$ {plan.total_amount:.2f}. Nenhum recebimento automático.")
    return plan


def installment_rows(plan):
    # Aggregation suppresses Meta.ordering; keep the schedule chronological on PostgreSQL.
    entries = plan.installments.select_related("entry").annotate(
        received=Sum("entry__payments__amount", filter=Q(entry__payments__reversal_of__isnull=True)),
        reversed=Sum("entry__payments__amount", filter=Q(entry__payments__reversal_of__isnull=False)),
    ).order_by("number", "pk")
    for item in entries:
        item.net_paid = (item.received or Decimal("0.00")) - (item.reversed or Decimal("0.00"))
        item.remaining = item.amount - item.net_paid
    return entries
