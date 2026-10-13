"""Explicit client grants and immutable review evidence; files stay in legal storage."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.legal.models import ImmutableQuerySet, ImmutableTenantModel, TenantModel


class RevocableRecord(TenantModel):
    objects = ImmutableQuerySet.as_manager()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="%(class)s_revoked")
    revoke_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if bool(self.revoked_at) != bool(self.revoked_by_id) or (self.revoked_at and not self.revoke_reason.strip()):
            raise ValidationError("A revogação exige responsável, data e motivo.")
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values().first()
            if original:
                if not getattr(self, "_allow_revoke", False) or original["revoked_at"]:
                    raise ValidationError("O vínculo é preservado; use a ação de revogação.")
                mutable = {"revoked_at", "revoked_by_id", "revoke_reason"}
                if any(getattr(self, key) != value for key, value in original.items() if key not in mutable):
                    raise ValidationError("A revogação não pode alterar os vínculos originais.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Revogue o acesso para preservar o histórico.")


class ClientAccess(RevocableRecord):
    membership = models.ForeignKey("core.Membership", on_delete=models.PROTECT, related_name="portal_accesses")
    contact = models.ForeignKey("legal.Contact", on_delete=models.PROTECT, related_name="portal_accesses")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="portal_accesses_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["membership", "contact"], condition=models.Q(revoked_at__isnull=True), name="portal_active_contact_membership")]

    def clean(self):
        super().clean()
        if self._state.adding and self.membership_id:
            member = self.membership
            if member.role != "client" or not member.is_active or not member.user.is_active:
                raise ValidationError("Escolha um membro ativo com perfil Cliente.")

    def __str__(self):
        return f"{self.contact.name} · {self.membership.user.email}"


class DocumentReview(ImmutableTenantModel):
    version = models.ForeignKey("legal.DocumentVersion", on_delete=models.PROTECT, related_name="portal_reviews")
    checksum = models.CharField(max_length=64)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="document_reviews_requested")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="document_reviews_assigned")
    note = models.TextField(max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def clean(self):
        super().clean()
        if self.version_id:
            if self.checksum != self.version.checksum:
                raise ValidationError("A revisão deve corresponder ao hash da versão enviada.")
            if self.reviewer_id in {self.requested_by_id, self.version.uploaded_by_id}:
                raise ValidationError("A revisão exige outra pessoa, diferente do solicitante e de quem enviou o arquivo.")
        if not self.note.strip():
            raise ValidationError("Descreva o que deve ser revisado.")


class ReviewDecision(ImmutableTenantModel):
    class Outcome(models.TextChoices):
        APPROVED = "approved", "Aprovado"
        REJECTED = "rejected", "Ajustes solicitados"

    review = models.OneToOneField(DocumentReview, on_delete=models.PROTECT, related_name="decision")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="document_review_decisions")
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    note = models.TextField(max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def clean(self):
        super().clean()
        if self.review_id and self.actor_id != self.review.reviewer_id:
            raise ValidationError("Somente a pessoa designada pode registrar a decisão.")
        if not self.note.strip():
            raise ValidationError("Registre a justificativa da decisão.")


class Publication(RevocableRecord):
    review = models.ForeignKey(DocumentReview, on_delete=models.PROTECT, related_name="publications")
    access = models.ForeignKey(ClientAccess, on_delete=models.PROTECT, related_name="publications")
    title = models.CharField("Título para o cliente", max_length=240)
    note = models.TextField("Mensagem de apresentação", max_length=3000, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="portal_publications")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["review", "access"], condition=models.Q(revoked_at__isnull=True), name="portal_active_review_access")]

    def clean(self):
        super().clean()
        if self._state.adding and self.review_id and self.access_id:
            if self.access.revoked_at or self.review.version.document.matter.client_id != self.access.contact_id:
                raise ValidationError("O acesso precisa estar ativo e vinculado ao cliente da pasta.")
            if not ReviewDecision.objects.filter(review_id=self.review_id, outcome=ReviewDecision.Outcome.APPROVED).exists():
                raise ValidationError("Somente uma versão aprovada pode ser publicada.")
        if not self.title.strip():
            raise ValidationError("Informe o título que o cliente verá.")


class PortalMessage(ImmutableTenantModel):
    publication = models.ForeignKey(Publication, on_delete=models.PROTECT, related_name="messages")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="portal_messages")
    body = models.TextField("Mensagem", max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def clean(self):
        super().clean()
        if not self.body.strip():
            raise ValidationError("Escreva uma mensagem.")
