"""Organization-scoped records for Jumbi's legal operations.

State transitions that change deadlines or money belong in services.py. Model
validation also protects imports, admin writes, and ordinary ORM creates.
"""

import hashlib
import uuid
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.db.models import Q, Sum
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.utils import timezone
from django.utils.deconstruct import deconstructible


MAX_DOCUMENT_SIZE = 15 * 1024 * 1024
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".png", ".jpg", ".jpeg", ".webp"}


@deconstructible
class PrivateDocumentStorage(FileSystemStorage):
    """Only an authorized download view may expose these files."""

    @property
    def base_location(self):
        return str(getattr(settings, "PRIVATE_MEDIA_ROOT", Path(settings.MEDIA_ROOT) / "private"))

    @property
    def location(self):
        return str(Path(self.base_location).resolve())

    def url(self, name):
        raise ValueError("Documentos privados devem ser baixados pela rota autenticada.")


private_storage = PrivateDocumentStorage()


def document_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"organizations/{instance.organization_id}/documents/{instance.document_id}/{uuid.uuid4().hex}{extension}"


def validate_document_file(file):
    if Path(file.name).suffix.lower() not in DOCUMENT_EXTENSIONS:
        raise ValidationError("Formato não permitido. Use PDF, DOCX, XLSX, TXT, PNG, JPG ou WEBP.")
    if file.size > MAX_DOCUMENT_SIZE:
        raise ValidationError("O arquivo deve ter no máximo 15 MB.")
    if file.size == 0:
        raise ValidationError("O arquivo está vazio.")


class TenantModel(models.Model):
    organization = models.ForeignKey(
        "core.Organization", on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_records",
    )

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if not self.organization_id:
            return
        errors = {}
        original_values = {}
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values().first()
            original_values = previous or {}
            old_org = original_values.get("organization_id")
            if old_org is not None and old_org != self.organization_id:
                errors["organization"] = "Não é permitido transferir registros entre escritórios."
            if "matter_id" in original_values and original_values["matter_id"] != getattr(self, "matter_id", None):
                errors["matter"] = "O vínculo com a pasta deve ser preservado para manter o histórico e as permissões."
        from apps.core.models import Membership

        for field in self._meta.fields:
            if not isinstance(field, models.ForeignKey) or field.name == "organization":
                continue
            related_id = getattr(self, field.attname)
            if related_id is None:
                continue
            related_model = field.remote_field.model
            if related_model._meta.label_lower == settings.AUTH_USER_MODEL.lower():
                memberships = Membership.objects.filter(organization_id=self.organization_id, user_id=related_id)
                if field.name == 'owner':
                    memberships = memberships.exclude(role='client')
                # Existing historical authors remain valid after revocation.
                # New assignments and current owners must be active users.
                unchanged_historical = field.name != "owner" and original_values.get(field.attname) == related_id
                if not unchanged_historical:
                    memberships = memberships.filter(is_active=True, user__is_active=True)
                if not memberships.exists():
                    errors[field.name] = "O usuário precisa integrar este escritório."
            elif any(f.name == "organization" for f in related_model._meta.fields):
                if not related_model.objects.filter(pk=related_id, organization_id=self.organization_id).exists():
                    errors[field.name] = "O registro relacionado pertence a outro escritório."
        # Assignment never grants access to a confidential matter implicitly.
        if hasattr(self, "matter_id") and self.matter_id and hasattr(self, "owner_id") and self.owner_id:
            matter = Matter.objects.filter(pk=self.matter_id, organization_id=self.organization_id).first()
            if matter and matter.confidential and matter.owner_id != self.owner_id:
                if not matter.members.filter(pk=self.owner_id).exists():
                    errors["owner"] = "O responsável precisa de acesso explícito à pasta sigilosa."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("O registro é imutável; crie um novo registro de correção.")

    def delete(self):
        raise ValidationError("O histórico deve ser preservado.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use os serviços de domínio para preservar validação e histórico.")


class ImmutableTenantModel(TenantModel):
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and (not self._state.adding or type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError("O registro é imutável; crie um novo registro de correção.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("O histórico deve ser preservado.")


class Contact(TenantModel):
    class Kind(models.TextChoices):
        PERSON = "person", "Pessoa física"
        COMPANY = "company", "Pessoa jurídica"

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        PROSPECT = "prospect", "Em atendimento inicial"
        INACTIVE = "inactive", "Inativo"

    name = models.CharField("Nome", max_length=200)
    email = models.EmailField("E-mail", blank=True)
    phone = models.CharField("Telefone", max_length=40, blank=True)
    document = models.CharField("CPF / CNPJ", max_length=30, blank=True)
    kind = models.CharField("Tipo", max_length=12, choices=Kind.choices, default=Kind.PERSON)
    birth_date = models.DateField("Data de nascimento", null=True, blank=True)
    trade_name = models.CharField("Nome fantasia", max_length=200, blank=True, default="", db_default="")
    profession = models.CharField("Profissão", max_length=150, blank=True, default="", db_default="")
    postal_code = models.CharField("CEP", max_length=20, blank=True, default="", db_default="")
    address = models.CharField("Logradouro e número", max_length=240, blank=True, default="", db_default="")
    address_complement = models.CharField("Complemento", max_length=150, blank=True, default="", db_default="")
    district = models.CharField("Bairro", max_length=100, blank=True, default="", db_default="")
    city = models.CharField("Cidade", max_length=120, blank=True, default="", db_default="")
    state = models.CharField("Estado / província", max_length=80, blank=True, default="", db_default="")
    country = models.CharField("País", max_length=80, blank=True, default="", db_default="")
    state_registration = models.CharField("Inscrição estadual", max_length=40, blank=True, default="", db_default="")
    municipal_registration = models.CharField("Inscrição municipal", max_length=40, blank=True, default="", db_default="")
    representatives = models.TextField("Representantes legais e procuradores", max_length=4000, blank=True, default="", db_default="")
    notes = models.TextField("Observações internas", max_length=6000, blank=True, default="", db_default="")
    status = models.CharField("Relacionamento", max_length=12, choices=Status.choices, default=Status.ACTIVE, db_default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.birth_date:
            if self.kind != self.Kind.PERSON:
                raise ValidationError({"birth_date": "Informe nascimento somente para pessoas físicas."})
            if self.birth_date > timezone.localdate():
                raise ValidationError({"birth_date": "A data de nascimento não pode estar no futuro."})


class Matter(TenantModel):
    class Nature(models.TextChoices):
        ADVISORY = "advisory", "Consultoria"
        LITIGATION = "litigation", "Contencioso"
        ADMINISTRATIVE = "administrative", "Administrativo"
        CONTRACT = "contract", "Contrato"

    class Status(models.TextChoices):
        ACTIVE = "active", "Em andamento"
        WAITING = "waiting", "Aguardando"
        CLOSED = "closed", "Encerrada"

    title = models.CharField("Título", max_length=240)
    client = models.ForeignKey(Contact, on_delete=models.PROTECT, null=True, blank=True, related_name="matters")
    nature = models.CharField("Natureza", max_length=20, choices=Nature.choices, default=Nature.ADVISORY)
    area = models.CharField("Área jurídica", max_length=100, blank=True)
    status = models.CharField("Situação", max_length=15, choices=Status.choices, default=Status.ACTIVE)
    description = models.TextField("Descrição", blank=True)
    confidential = models.BooleanField("Pasta sigilosa", default=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_matters")
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="authorized_matters")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["organization", "status"])]

    def __str__(self):
        return self.title

    @property
    def area_label(self):
        from apps.core.niches import PRACTICE_AREA_LABELS
        return PRACTICE_AREA_LABELS.get(self.area, self.area)


@receiver(m2m_changed, sender=Matter.members.through)
def validate_matter_members(sender, instance, action, reverse, pk_set, **kwargs):
    if action != "pre_add":
        return
    from apps.core.models import Membership

    if reverse:
        for matter in Matter.objects.filter(pk__in=pk_set):
            if not Membership.objects.filter(organization_id=matter.organization_id, user=instance, is_active=True, user__is_active=True).exists():
                raise ValidationError("A equipe da pasta deve pertencer ao mesmo escritório.")
    else:
        active_ids = set(Membership.objects.filter(
            organization_id=instance.organization_id, user_id__in=pk_set, is_active=True, user__is_active=True
        ).values_list("user_id", flat=True))
        if active_ids != set(pk_set):
            raise ValidationError("A equipe da pasta deve pertencer ao mesmo escritório.")


class CourtCase(TenantModel):
    matter = models.ForeignKey(Matter, on_delete=models.PROTECT, related_name="court_cases")
    number = models.CharField("Número", max_length=80)
    court = models.CharField("Tribunal / órgão", max_length=180, blank=True)
    opposing_party = models.CharField("Parte contrária", max_length=240, blank=True)
    notes = models.TextField("Anotações", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number"]
        constraints = [models.UniqueConstraint(fields=["organization", "number"], name="legal_case_org_number_unique")]

    def __str__(self):
        return self.number


class Task(TenantModel):
    class Status(models.TextChoices):
        TODO = "todo", "A fazer"
        DOING = "doing", "Em execução"
        DONE = "done", "Concluída"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"
        URGENT = "urgent", "Urgente"

    matter = models.ForeignKey(Matter, on_delete=models.PROTECT, null=True, blank=True, related_name="tasks")
    title = models.CharField("Título", max_length=240)
    description = models.TextField("Descrição", blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="legal_tasks")
    due_date = models.DateField("Vencimento")
    status = models.CharField("Situação", max_length=12, choices=Status.choices, default=Status.TODO)
    priority = models.CharField("Prioridade", max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    completion_note = models.TextField("Evidência de conclusão", blank=True)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "pk"]
        indexes = [models.Index(fields=["organization", "status", "due_date"])]

    def clean(self):
        super().clean()
        if self.status == self.Status.DONE and not self.completion_note.strip():
            raise ValidationError({"completion_note": "Descreva a evidência de conclusão."})

    def __str__(self):
        return self.title


class Deadline(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "A conferir"
        CONFIRMED = "confirmed", "Conferido"
        FULFILLED = "fulfilled", "Cumprido"

    matter = models.ForeignKey(Matter, on_delete=models.PROTECT, related_name="deadlines")
    title = models.CharField("Obrigação", max_length=240)
    source = models.TextField("Origem / publicação")
    due_date = models.DateField("Vencimento")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="legal_deadlines")
    status = models.CharField("Situação", max_length=15, choices=Status.choices, default=Status.PENDING)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="confirmed_deadlines")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    evidence = models.TextField("Evidência do cumprimento", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "pk"]
        indexes = [models.Index(fields=["organization", "status", "due_date"])]

    def clean(self):
        super().clean()
        if not self.source.strip():
            raise ValidationError({"source": "Registre a origem do prazo."})
        if self.status != self.Status.PENDING and (not self.confirmed_by_id or not self.confirmed_at):
            raise ValidationError({"status": "O prazo precisa de conferência humana registrada."})
        if self.status == self.Status.FULFILLED and not self.evidence.strip():
            raise ValidationError({"evidence": "Registre a evidência do cumprimento da obrigação."})
        if self.pk and not self._state.adding:
            original = Deadline.objects.filter(pk=self.pk).values("due_date", "status", "confirmed_by_id", "confirmed_at", "evidence").first()
            if original and not getattr(self, "_allow_transition", False):
                if any(original[field] != getattr(self, field) for field in original):
                    raise ValidationError("Use os serviços de conferência, revisão e cumprimento para alterar o prazo.")

    def __str__(self):
        return self.title


class DeadlineRevision(ImmutableTenantModel):
    deadline = models.ForeignKey(Deadline, on_delete=models.PROTECT, related_name="revisions")
    previous_date = models.DateField()
    new_date = models.DateField()
    reason = models.TextField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="deadline_revisions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def clean(self):
        super().clean()
        if not self.reason.strip():
            raise ValidationError({"reason": "Informe o motivo da revisão."})
        if self.previous_date == self.new_date:
            raise ValidationError({"new_date": "O novo vencimento deve ser diferente do anterior."})


class Appointment(TenantModel):
    class Kind(models.TextChoices):
        MEETING = "meeting", "Reunião"
        HEARING = "hearing", "Audiência"
        IMPORTANT_DATE = "important_date", "Data importante"
        OTHER = "other", "Outro compromisso"

    matter = models.ForeignKey(Matter, on_delete=models.PROTECT, null=True, blank=True, related_name="appointments")
    title = models.CharField("Compromisso", max_length=240)
    kind = models.CharField("Tipo", max_length=20, choices=Kind.choices, default=Kind.OTHER, db_default="other")
    starts_at = models.DateTimeField("Início")
    ends_at = models.DateTimeField("Término")
    location = models.CharField("Local", max_length=240, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="legal_appointments")

    class Meta:
        ordering = ["starts_at", "pk"]

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "O término deve ser posterior ao início."})

    def __str__(self):
        return self.title


class Document(TenantModel):
    matter = models.ForeignKey(Matter, on_delete=models.PROTECT, related_name="documents")
    title = models.CharField("Título", max_length=240)
    kind = models.CharField("Classificação", max_length=80, default="general")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="legal_documents")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    @property
    def latest_version(self):
        return self.versions.order_by("-number").first()

    def __str__(self):
        return self.title


class DocumentVersion(ImmutableTenantModel):
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    file = models.FileField(storage=private_storage, upload_to=document_upload_path, validators=[validate_document_file], max_length=500)
    original_name = models.CharField(max_length=255)
    checksum = models.CharField(max_length=64, editable=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_legal_versions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["document", "number"], name="legal_document_version_unique"),
            models.CheckConstraint(condition=Q(number__gte=1), name="legal_document_version_positive"),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding and self.file:
            self.original_name = Path(self.file.name.replace("\\", "/")).name[:255]
            validate_document_file(self.file)
            digest = hashlib.sha256()
            self.file.open("rb")
            for chunk in self.file.chunks():
                digest.update(chunk)
            self.file.seek(0)
            self.checksum = digest.hexdigest()
        return super().save(*args, **kwargs)


class AuditEvent(ImmutableTenantModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="legal_audit_events")
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["organization", "object_type", "object_id"])]


class FinanceEntry(TenantModel):
    class Kind(models.TextChoices):
        INCOME = "income", "Receita do escritório"
        EXPENSE = "expense", "Despesa do escritório"
        CLIENT_FUND = "client_fund", "Valor de cliente"

    matter = models.ForeignKey(Matter, on_delete=models.PROTECT, null=True, blank=True, related_name="finance_entries")
    description = models.CharField("Descrição", max_length=240)
    kind = models.CharField("Tipo", max_length=20, choices=Kind.choices, default=Kind.INCOME)
    amount = models.DecimalField("Valor", max_digits=14, decimal_places=2)
    due_date = models.DateField("Vencimento")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date", "pk"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="legal_finance_amount_positive")]

    def clean(self):
        super().clean()
        from apps.fees.models import validate_fee_entry
        validate_fee_entry(self)
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "O valor deve ser maior que zero."})
        if self.pk and not self._state.adding:
            previous = FinanceEntry.objects.filter(pk=self.pk).values("amount", "kind", "matter_id").first()
            if previous and self.payments.exists() and any(previous[f] != getattr(self, f) for f in previous):
                raise ValidationError("O valor, o tipo e a pasta de um lançamento movimentado devem ser preservados.")

    @property
    def paid_amount(self):
        if not self.pk:
            return Decimal("0.00")
        totals = self.payments.aggregate(
            received=Sum("amount", filter=Q(reversal_of__isnull=True)),
            reversed=Sum("amount", filter=Q(reversal_of__isnull=False)),
        )
        return (totals["received"] or Decimal("0.00")) - (totals["reversed"] or Decimal("0.00"))

    @property
    def balance(self):
        return self.amount - self.paid_amount

    @property
    def is_paid(self):
        return self.balance == Decimal("0.00")

    def __str__(self):
        return self.description


class Payment(ImmutableTenantModel):
    operation_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(FinanceEntry, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField("Valor", max_digits=14, decimal_places=2)
    date = models.DateField("Data", default=timezone.localdate, null=True, blank=True)
    note = models.TextField("Observação", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="legal_payments")
    is_legacy_import = models.BooleanField("Baixa importada do cadastro anterior", default=False, editable=False)
    reversal_of = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="legal_payment_amount_positive")]

    def clean(self):
        super().clean()
        if not self.is_legacy_import and (self.date is None or self.created_by_id is None):
            raise ValidationError("Baixas atuais exigem data e operador responsável.")
        if self.is_legacy_import and not self.note.strip():
            raise ValidationError({"note": "A baixa importada precisa registrar sua proveniência e limitações."})
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "A baixa deve ser maior que zero."})
        if self.reversal_of_id:
            original = Payment.objects.filter(pk=self.reversal_of_id).first()
            if original:
                if original.entry_id != self.entry_id:
                    raise ValidationError({"reversal_of": "O estorno deve pertencer ao lançamento original."})
                if original.reversal_of_id or original.amount != self.amount:
                    raise ValidationError({"reversal_of": "Estorne uma baixa original pelo seu valor integral."})
                if not self.note.strip():
                    raise ValidationError({"note": "Informe o motivo do estorno."})
        elif self._state.adding and self.entry_id and self.amount is not None:
            entry = FinanceEntry.objects.filter(pk=self.entry_id, organization_id=self.organization_id).first()
            if entry and self.amount > entry.balance:
                raise ValidationError({"amount": "A baixa não pode exceder o saldo do lançamento."})


class Opportunity(TenantModel):
    class Stage(models.TextChoices):
        NEW = "new", "Nova"
        QUALIFICATION = "qualification", "Qualificação"
        PROPOSAL = "proposal", "Proposta"
        WON = "won", "Ganha"
        LOST = "lost", "Perdida"

    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="opportunities")
    title = models.CharField("Oportunidade", max_length=240)
    stage = models.CharField("Etapa", max_length=20, choices=Stage.choices, default=Stage.NEW)
    amount = models.DecimalField("Valor estimado", max_digits=14, decimal_places=2, default=Decimal("0.00"))
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="legal_opportunities")
    next_action = models.CharField("Próxima ação", max_length=240, blank=True)
    lost_reason = models.TextField("Motivo da perda", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.CheckConstraint(condition=Q(amount__gte=0), name="legal_opportunity_amount_nonnegative")]

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount < 0:
            raise ValidationError({"amount": "O valor estimado não pode ser negativo."})
        if self.stage == self.Stage.LOST and not self.lost_reason.strip():
            raise ValidationError({"lost_reason": "Informe o motivo da perda."})

    def __str__(self):
        return self.title


class LegacyImportRecord(ImmutableTenantModel):
    """Immutable provenance and idempotency key for an explicit legacy import."""

    source_model = models.CharField(max_length=100)
    source_id = models.PositiveBigIntegerField()
    source_data = models.JSONField(default=dict)
    target_model = models.CharField(max_length=100)
    target_id = models.PositiveBigIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                              related_name="legacy_import_records")
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["imported_at", "pk"]
        constraints = [models.UniqueConstraint(
            fields=["organization", "source_model", "source_id"], name="legal_legacy_source_unique",
        )]

    def clean(self):
        super().clean()
        from django.apps import apps

        try:
            model = apps.get_model(self.target_model)
        except (LookupError, ValueError):
            raise ValidationError({"target_model": "Modelo de destino inválido."}) from None
        if not issubclass(model, TenantModel) or not model.objects.filter(
            pk=self.target_id, organization_id=self.organization_id,
        ).exists():
            raise ValidationError({"target_id": "O destino deve pertencer ao mesmo escritório."})
