from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import Organization
from apps.office.models import Client, LegalCase, MatterType, PracticeArea


class PartnerNetworkSettings(models.Model):
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="partner_network",
    )
    is_enabled = models.BooleanField("rede habilitada", default=False)
    public_name = models.CharField("nome da rede", max_length=120, default="Rede de Parceiros")
    presentation = models.TextField(
        "apresentação ao parceiro",
        blank=True,
        default="Registre oportunidades e acompanhe somente as informações autorizadas pelo escritório.",
    )
    acceptance_rules = models.TextField("critérios de aceitação", blank=True)
    relationship_policy = models.TextField("política de relacionamento", blank=True)
    privacy_notice_version = models.CharField("versão do aviso de privacidade", max_length=30, default="1.0")
    financial_policy_enabled = models.BooleanField(
        "existe política financeira contratual",
        default=False,
        help_text="Não ativa comissão automática nem vincula pagamentos a honorários.",
    )
    financial_policy = models.TextField(
        "política financeira contratual",
        blank=True,
        help_text="Use apenas para reembolsos ou serviços formalmente contratados e aprovados pelo escritório.",
    )
    compliance_acknowledged = models.BooleanField("conformidade reconhecida", default=False)
    compliance_acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_network_compliance_acceptances",
    )
    compliance_acknowledged_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuração da rede de parceiros"
        verbose_name_plural = "configurações das redes de parceiros"

    def __str__(self):
        return f"{self.public_name} · {self.organization}"


class PartnerCategory(models.Model):
    class Kind(models.TextChoices):
        INSTITUTIONAL = "institutional", "Institucional"
        BUSINESS = "business", "Empresa ou profissional"
        LEGAL_CORRESPONDENT = "legal_correspondent", "Correspondente jurídico"
        COMMUNITY = "community", "Entidade ou comunidade"
        OTHER = "other", "Outra categoria"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="partner_categories",
    )
    name = models.CharField("nome", max_length=100)
    kind = models.CharField("tipo", max_length=24, choices=Kind.choices, default=Kind.BUSINESS)
    description = models.CharField("descrição", max_length=240, blank=True)
    is_active = models.BooleanField("ativa", default=True)
    sort_order = models.PositiveSmallIntegerField("ordem", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_partner_category_per_org",
            )
        ]

    def __str__(self):
        return f"{self.name} · {self.organization}"


class Partner(models.Model):
    class PersonType(models.TextChoices):
        PERSON = "person", "Pessoa física"
        COMPANY = "company", "Pessoa jurídica"

    class Status(models.TextChoices):
        PENDING = "pending", "Em análise"
        APPROVED = "approved", "Aprovado"
        REJECTED = "rejected", "Rejeitado"
        SUSPENDED = "suspended", "Suspenso"
        BLOCKED = "blocked", "Bloqueado"
        INACTIVE = "inactive", "Desativado"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="partners",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="partner_profiles",
    )
    category = models.ForeignKey(
        PartnerCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partners",
    )
    person_type = models.CharField("perfil", max_length=12, choices=PersonType.choices, default=PersonType.PERSON)
    display_name = models.CharField("nome", max_length=160)
    legal_name = models.CharField("razão social", max_length=180, blank=True)
    document_masked = models.CharField("documento protegido", max_length=24, blank=True)
    document_hash = models.CharField(max_length=64, blank=True, editable=False)
    email = models.EmailField("e-mail")
    phone = models.CharField("telefone", max_length=30, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=30, blank=True)
    city = models.CharField("cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    address = models.CharField("endereço", max_length=240, blank=True)
    status = models.CharField("status", max_length=16, choices=Status.choices, default=Status.PENDING)
    origin = models.CharField("origem do relacionamento", max_length=120, blank=True)
    internal_notes = models.TextField("observações internas", blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    privacy_accepted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_partners",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    last_access_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_partner_user_per_org",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"], name="partner_org_status_idx"),
            models.Index(fields=["organization", "document_hash"], name="partner_org_doc_idx"),
        ]

    def __str__(self):
        return f"{self.display_name} · {self.organization}"


class PartnerCampaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        ACTIVE = "active", "Ativa"
        PAUSED = "paused", "Pausada"
        CLOSED = "closed", "Encerrada"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="partner_campaigns",
    )
    name = models.CharField("nome", max_length=140)
    practice_area = models.ForeignKey(
        PracticeArea,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_campaigns",
        verbose_name="área jurídica",
    )
    description = models.TextField("orientação ao parceiro")
    acceptance_criteria = models.TextField("critérios de aceitação", blank=True)
    required_documents = models.JSONField("documentos orientativos", default=list, blank=True)
    eligible_categories = models.ManyToManyField(
        PartnerCategory,
        blank=True,
        related_name="campaigns",
        verbose_name="categorias elegíveis",
    )
    status = models.CharField("status", max_length=12, choices=Status.choices, default=Status.DRAFT)
    starts_at = models.DateField("início", null=True, blank=True)
    ends_at = models.DateField("fim", null=True, blank=True)
    opportunity_limit = models.PositiveIntegerField("limite total", null=True, blank=True)
    per_partner_limit = models.PositiveIntegerField("limite por parceiro", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_partner_campaigns",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"], name="campaign_org_status_idx"),
        ]

    def __str__(self):
        return f"{self.name} · {self.organization}"


class PartnerOpportunity(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Nova"
        ANALYSIS = "analysis", "Em análise"
        CONTACTED = "contacted", "Contato realizado"
        DOCUMENTS_PENDING = "documents_pending", "Documentos pendentes"
        WAITING = "waiting", "Aguardando retorno"
        CONSULTATION = "consultation", "Consulta agendada"
        PROPOSAL = "proposal", "Proposta enviada"
        CONTRACT = "contract", "Contrato em formalização"
        CONVERTED = "converted", "Convertida"
        CASE_CREATED = "case_created", "Caso criado"
        CANCELLED = "cancelled", "Cancelada"
        LOST = "lost", "Não convertida"
        DUPLICATE = "duplicate", "Possível duplicidade"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="partner_opportunities",
    )
    partner = models.ForeignKey(Partner, on_delete=models.PROTECT, related_name="opportunities")
    campaign = models.ForeignKey(
        PartnerCampaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opportunities",
    )
    practice_area = models.ForeignKey(
        PracticeArea,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_opportunities",
        verbose_name="área jurídica",
    )
    matter_type = models.ForeignKey(
        MatterType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_opportunities",
        verbose_name="tipo de demanda",
    )
    interested_party_name = models.CharField("nome da pessoa interessada", max_length=160)
    email = models.EmailField("e-mail", blank=True)
    phone = models.CharField("telefone/WhatsApp", max_length=30, blank=True)
    city = models.CharField("cidade", max_length=100, blank=True)
    state = models.CharField("UF", max_length=2, blank=True)
    document_masked = models.CharField("documento protegido", max_length=24, blank=True)
    document_hash = models.CharField(max_length=64, blank=True, editable=False)
    description = models.TextField("resumo da necessidade")
    source = models.CharField("origem", max_length=120, blank=True)
    status = models.CharField("status", max_length=24, choices=Status.choices, default=Status.NEW)
    possible_duplicate = models.BooleanField("possível duplicidade", default=False)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_partner_opportunities",
    )
    partner_message = models.TextField("mensagem visível ao parceiro", blank=True)
    internal_notes = models.TextField("observações internas", blank=True)
    consent_confirmed = models.BooleanField("consentimento confirmado", default=False)
    consent_version = models.CharField("versão do consentimento", max_length=30, blank=True)
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_ip = models.GenericIPAddressField(null=True, blank=True)
    converted_client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_opportunities",
    )
    converted_case = models.ForeignKey(
        LegalCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_opportunities",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    contacted_at = models.DateTimeField(null=True, blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status", "created_at"], name="opportunity_queue_idx"),
            models.Index(fields=["partner", "status"], name="opportunity_partner_idx"),
            models.Index(fields=["organization", "document_hash"], name="opportunity_doc_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(email__gt="") | Q(phone__gt=""),
                name="opportunity_requires_contact",
            ),
        ]

    @property
    def public_status(self):
        if self.status in {self.Status.NEW, self.Status.ANALYSIS}:
            return "Recebida pelo escritório"
        if self.status in {
            self.Status.CONTACTED,
            self.Status.DOCUMENTS_PENDING,
            self.Status.WAITING,
            self.Status.CONSULTATION,
        }:
            return "Em atendimento"
        if self.status in {self.Status.PROPOSAL, self.Status.CONTRACT}:
            return "Em formalização"
        if self.status in {self.Status.CONVERTED, self.Status.CASE_CREATED}:
            return "Convertida"
        return "Encerrada"

    def __str__(self):
        return f"{self.interested_party_name} · {self.partner}"


class PartnerOpportunityEvent(models.Model):
    opportunity = models.ForeignKey(
        PartnerOpportunity,
        on_delete=models.CASCADE,
        related_name="events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_opportunity_events",
    )
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, choices=PartnerOpportunity.Status.choices)
    public_message = models.TextField("mensagem ao parceiro", blank=True)
    internal_message = models.TextField("registro interno", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["opportunity", "created_at"], name="opportunity_event_idx"),
        ]

    def __str__(self):
        return f"{self.opportunity} · {self.to_status}"


class PartnerMaterial(models.Model):
    class Kind(models.TextChoices):
        GUIDE = "guide", "Guia"
        TRAINING = "training", "Treinamento"
        CAMPAIGN = "campaign", "Campanha"
        POLICY = "policy", "Política"
        OTHER = "other", "Outro"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="partner_materials",
    )
    campaign = models.ForeignKey(
        PartnerCampaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="materials",
    )
    title = models.CharField("título", max_length=160)
    description = models.CharField("descrição", max_length=240, blank=True)
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices, default=Kind.GUIDE)
    url = models.URLField("link seguro")
    is_active = models.BooleanField("visível", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
