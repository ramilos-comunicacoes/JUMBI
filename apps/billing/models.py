from django.conf import settings
from django.db import models
from django.utils import timezone
from .plans import PLANS, PLAN_CHOICES, PARTNER_LIMITS


class OrganizationSubscription(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando contratação"
        ACTIVE = "active", "Ativa"
        DEMO = "demo", "Demonstração"
        SUSPENDED = "suspended", "Suspensa"

    organization = models.OneToOneField("core.Organization", on_delete=models.PROTECT, related_name="subscription", verbose_name="Escritório")
    plan = models.CharField("Plano", max_length=12, choices=PLAN_CHOICES, default="start")
    status = models.CharField("Situação", max_length=15, choices=Status.choices, default=Status.PENDING)
    requested_plan = models.CharField("Mudança solicitada", max_length=12, choices=PLAN_CHOICES, blank=True)
    is_partner = models.BooleanField("Parceiro — gratuito e ilimitado", default=False, db_default=False,
        help_text="Libera todos os recursos do Max, sem cobrança, vencimento ou limites comerciais de usuários, pastas e documentos. A suspensão e as permissões continuam valendo.")
    expires_at = models.DateTimeField("Acesso válido até", null=True, blank=True, help_text="Sem data: gestão manual da vigência. Isso não registra pagamento.")
    notes = models.TextField("Observações da contratação", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Assinatura"
        verbose_name_plural = "Assinaturas"

    @property
    def is_available(self):
        return self.status in {self.Status.ACTIVE, self.Status.DEMO} and (self.is_partner or self.expires_at is None or self.expires_at > timezone.now())

    @property
    def limits(self):
        return PARTNER_LIMITS.copy() if self.is_partner else PLANS[self.plan]

    def clean(self):
        super().clean()
        if self.is_partner:
            self.plan = "max"
            self.expires_at = None
            self.requested_plan = ""

    def __str__(self):
        return f"{self.organization} · {self.limits['name']} · {self.get_status_display()}"


class SubscriptionEvent(models.Model):
    subscription = models.ForeignKey(OrganizationSubscription, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Histórico da assinatura"
        verbose_name_plural = "Histórico de assinaturas"
