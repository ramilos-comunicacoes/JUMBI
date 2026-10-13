import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.legal.models import ImmutableTenantModel


class FeePlan(ImmutableTenantModel):
    class Kind(models.TextChoices):
        INSTALLMENTS = "installments", "Honorários parcelados"
        MONTHLY = "monthly", "Assessoria mensal"

    operation_key = models.UUIDField(default=uuid.uuid4, editable=False)
    request_hash = models.CharField(max_length=64, editable=False)
    title = models.CharField("Descrição do acordo", max_length=180)
    matter = models.ForeignKey("legal.Matter", on_delete=models.PROTECT, related_name="fee_plans")
    client = models.ForeignKey("legal.Contact", on_delete=models.PROTECT, related_name="fee_plans")
    kind = models.CharField("Modalidade", max_length=20, choices=Kind.choices)
    amount = models.DecimalField("Valor informado", max_digits=14, decimal_places=2)
    total_amount = models.DecimalField("Total previsto", max_digits=14, decimal_places=2)
    periods = models.PositiveSmallIntegerField("Quantidade de meses")
    first_due_date = models.DateField("Primeiro vencimento")
    notes = models.TextField("Condições do acordo", blank=True, max_length=3000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_fee_plans")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "operation_key"], name="fees_operation_unique"),
            models.CheckConstraint(condition=Q(amount__gt=0) & Q(total_amount__gt=0), name="fees_plan_amounts_positive"),
            models.CheckConstraint(condition=Q(periods__gte=1) & Q(periods__lte=36), name="fees_periods_range"),
        ]

    def clean(self):
        super().clean()
        from .services import build_schedule
        schedule = build_schedule(kind=self.kind, amount=self.amount, periods=self.periods, first_due_date=self.first_due_date)
        if self.total_amount != sum(row["amount"] for row in schedule):
            raise ValidationError({"total_amount": "O total precisa corresponder ao cronograma."})
        if self.matter_id and self.client_id:
            from apps.legal.models import Matter
            matter = Matter.objects.filter(pk=self.matter_id, organization_id=self.organization_id).first()
            if matter and matter.client_id and matter.client_id != self.client_id:
                raise ValidationError({"client": "Selecione o cliente da pasta."})

    def __str__(self):
        return self.title


class FeeInstallment(ImmutableTenantModel):
    plan = models.ForeignKey(FeePlan, on_delete=models.PROTECT, related_name="installments")
    entry = models.OneToOneField("legal.FinanceEntry", on_delete=models.PROTECT, related_name="fee_installment")
    number = models.PositiveSmallIntegerField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "number"], name="fees_installment_number_unique"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="fees_installment_amount_positive"),
            models.CheckConstraint(condition=Q(number__gte=1) & Q(number__lte=36), name="fees_installment_number_range"),
        ]

    def clean(self):
        super().clean()
        if self.plan_id and self.entry_id:
            from .services import build_schedule
            plan = FeePlan.objects.get(pk=self.plan_id)
            schedule = build_schedule(kind=plan.kind, amount=plan.amount, periods=plan.periods, first_due_date=plan.first_due_date)
            if not self.number or self.number > len(schedule):
                raise ValidationError("Parcela fora do cronograma.")
            row = schedule[self.number - 1]
            if self.amount != row["amount"] or self.due_date != row["due_date"]:
                raise ValidationError("A parcela precisa preservar o cronograma aprovado.")
            entry = self.entry
            if entry.kind != "income" or entry.matter_id != plan.matter_id or entry.amount != self.amount or entry.due_date != self.due_date:
                raise ValidationError("O lançamento precisa corresponder à parcela de honorários.")


def validate_fee_entry(entry):
    """Called by FinanceEntry.clean to preserve the approved installment record."""
    if not entry.pk:
        return
    installment = FeeInstallment.objects.filter(entry_id=entry.pk).select_related("plan").first()
    if installment and (entry.amount != installment.amount or entry.due_date != installment.due_date or entry.kind != "income" or entry.matter_id != installment.plan.matter_id):
        raise ValidationError("O lançamento pertence a um acordo de honorários. Preserve valor, vencimento, tipo e pasta; use baixas e estornos para movimentá-lo.")
