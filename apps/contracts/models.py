import hashlib
import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.legal.models import ImmutableTenantModel, TenantModel


class ContractTemplate(TenantModel):
    name = models.CharField("Nome do modelo", max_length=180)
    category = models.CharField("Área / categoria", max_length=100, blank=True)
    description = models.CharField("Descrição breve", max_length=300, blank=True)
    body = models.TextField("Texto e cláusulas", max_length=100000)
    is_active = models.BooleanField("Disponível para novos contratos", default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contract_templates")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        from .services import validate_source
        validate_source(self.body)


class Contract(TenantModel):
    title = models.CharField("Título", max_length=220)
    template = models.ForeignKey(ContractTemplate, on_delete=models.PROTECT, related_name="contracts")
    matter = models.ForeignKey("legal.Matter", on_delete=models.PROTECT, related_name="contracts")
    client = models.ForeignKey("legal.Contact", on_delete=models.PROTECT, related_name="contracts")
    document = models.OneToOneField("legal.Document", on_delete=models.PROTECT, related_name="contract")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contracts")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.matter_id and self.client_id and self.matter.client_id and self.matter.client_id != self.client_id:
            raise ValidationError({"client": "Selecione o cliente vinculado à pasta."})
        if self.document_id and self.document.matter_id != self.matter_id:
            raise ValidationError({"document": "O documento deve pertencer à mesma pasta."})
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values("template_id", "client_id", "document_id").first()
            if previous and any(previous[field] != getattr(self, field) for field in previous):
                raise ValidationError("Os vínculos do contrato devem ser preservados. Crie um novo contrato para outra parte ou modelo.")


class ContractRevision(ImmutableTenantModel):
    operation_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="revisions")
    document_version = models.OneToOneField("legal.DocumentVersion", on_delete=models.PROTECT, related_name="contract_revision")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=220)
    template_name = models.CharField(max_length=180)
    source_body = models.TextField(max_length=100000)
    values = models.JSONField(default=dict, blank=True)
    rendered_text = models.TextField(max_length=200000)
    checksum = models.CharField(max_length=64, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contract_revisions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "number"], name="contracts_revision_number_unique"),
            models.CheckConstraint(condition=models.Q(number__gte=1), name="contracts_revision_positive"),
        ]

    def __str__(self):
        return f"{self.title} · versão {self.number}"

    def clean(self):
        super().clean()
        from .services import render_body
        if self.contract_id and self.document_version_id and self.document_version.document_id != self.contract.document_id:
            raise ValidationError("A versão do documento deve pertencer ao contrato.")
        if render_body(self.source_body, self.values) != self.rendered_text:
            raise ValidationError("O texto não corresponde aos campos e cláusulas da versão.")

    def save(self, *args, **kwargs):
        canonical = json.dumps({
            "title": self.title, "template_name": self.template_name,
            "source": self.source_body, "values": self.values, "rendered": self.rendered_text,
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return super().save(*args, **kwargs)
