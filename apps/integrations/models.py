"""Models for JUMBI Judicial Integrations (v2.0).

Strict multi-tenant architecture with cryptographic isolation, immutable audit trail,
separate documentary/authorized statuses, and robust tracking for 33 courts.
"""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.legal.models import CourtCase, Deadline, Matter, TenantModel


class IntegrationProvider(models.Model):
    """Catalog of supported judicial and institutional integration providers."""
    class DocumentationStatus(models.TextChoices):
        DOCUMENTED = "documented", "Documentado oficialmente"
        AWAITING_CONTRACT = "awaiting_contract", "Aguardando contrato/WSDL"
        BLOCKED = "blocked", "Bloqueado para uso comercial"

    code = models.CharField("Código do Provedor", max_length=50, unique=True)
    name = models.CharField("Nome", max_length=120)
    documentation_status = models.CharField("Situação Documental", max_length=40, default=DocumentationStatus.DOCUMENTED)
    authorization_status = models.CharField("Situação de Autorização", max_length=60, default="PENDING_CREDENTIALS")
    capabilities = models.JSONField("Capacidades Suportadas", default=list)
    policy = models.TextField("Política de Uso e Limites", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class ExternalContractVersion(models.Model):
    """Captured and validated OpenAPI / WSDL contracts for integrations."""
    provider = models.ForeignKey(IntegrationProvider, on_delete=models.PROTECT, related_name="contracts")
    source_url = models.URLField("URL de Origem do Contrato", max_length=500)
    environment = models.CharField("Ambiente", max_length=20, default="production")
    version = models.CharField("Versão do Contrato", max_length=40, default="1.0.0")
    sha256 = models.CharField("Hash SHA-256", max_length=64)
    raw_content = models.TextField("Contrato Bruto (YAML/JSON/WSDL)", blank=True)
    field_mappings = models.JSONField("Mapeamento de Campos Aprovados", default=dict)
    is_approved = models.BooleanField("Aprovado para Produção", default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    approved_at = models.DateTimeField("Data de Aprovação", null=True, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-captured_at"]

    def __str__(self):
        return f"{self.provider.code} v{self.version} ({'Aprovado' if self.is_approved else 'Rascunho'})"


class SourceDeployment(models.Model):
    """Inventory of court deployments (27 TJs, 6 TRFs and federal branches)."""
    tribunal = models.CharField("Sigla do Tribunal", max_length=30)
    uf = models.CharField("UF", max_length=5, blank=True, null=True)
    branch = models.CharField("Ramo da Justiça", max_length=30, default="estadual")
    system = models.CharField("Sistema Processual", max_length=80)
    grade = models.CharField("Grau de Jurisdição", max_length=20, blank=True, null=True)
    environment = models.CharField("Ambiente", max_length=20, default="production")
    endpoint_url = models.URLField("Endpoint Principal", max_length=500, blank=True, null=True)
    wsdl_url = models.URLField("URL do WSDL", max_length=500, blank=True, null=True)
    inventory_status = models.CharField("Status do Inventário", max_length=80, default="inherited_documentary_not_reverified_v2")
    live_integration = models.BooleanField("Integração Ativa e Homologada", default=False)
    djen_capability = models.CharField("Status no DJEN", max_length=120, default="national_source_requires_filter_and_coverage_validation")
    notes = models.TextField("Observações Técnicas", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["branch", "tribunal", "grade"]
        constraints = [
            models.UniqueConstraint(fields=["tribunal", "branch", "grade", "environment"], name="integrations_source_deployment_uniq"),
        ]

    def __str__(self):
        return f"{self.tribunal} ({self.system}) - {self.branch.upper()}"

    @property
    def court_code(self):
        return self.tribunal

    @property
    def base_url(self):
        return self.endpoint_url


class IntegrationCapability(models.Model):
    """Fine-grained capability matrix per court deployment."""
    deployment = models.ForeignKey(SourceDeployment, on_delete=models.CASCADE, related_name="capabilities")
    capability = models.CharField("Capacidade", max_length=60)
    documentation_status = models.CharField("Situação Documental", max_length=60, default="DOCUMENTED")
    authorization_status = models.CharField("Situação de Autorização", max_length=60, default="PENDING_CREDENTIALS")
    health_status = models.CharField("Saúde Operacional", max_length=60, default="NOT_HOMOLOGATED")
    last_verified_at = models.DateTimeField("Última Verificação", null=True, blank=True)

    class Meta:
        ordering = ["deployment", "capability"]
        constraints = [
            models.UniqueConstraint(fields=["deployment", "capability"], name="integrations_capability_uniq"),
        ]

    def __str__(self):
        return f"{self.deployment.tribunal} · {self.capability} ({self.health_status})"

    @property
    def capability_type(self):
        return self.capability


class IntegrationAccount(TenantModel):
    """Tenant-scoped external credentials and institutional connection settings."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(IntegrationProvider, on_delete=models.PROTECT, related_name="accounts")
    label = models.CharField("Identificação da Conta", max_length=150)
    environment = models.CharField("Ambiente", max_length=20, default="sandbox", choices=[("sandbox", "Homologação"), ("production", "Produção")])
    external_principal_id = models.CharField("Identificador do Titular / CNPJ", max_length=120, blank=True)
    status = models.CharField("Situação", max_length=50, default="PENDING_CREDENTIALS")
    encrypted_credentials = models.TextField("Credenciais Protegidas (write-only)", blank=True)
    secret_key_ref = models.CharField("Referência da Chave", max_length=120, blank=True)
    scopes = models.JSONField("Escopos Habilitados", default=list, blank=True)
    has_credentials = models.BooleanField("Possui Credenciais Cadastradas", default=False)
    enabled = models.BooleanField("Ativa", default=True)
    revoked_at = models.DateTimeField("Data de Revogação", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} [{self.provider.code}] ({self.environment})"


class MonitoringRule(TenantModel):
    """Rule for automated or scheduled court & publication monitoring."""
    class Kind(models.TextChoices):
        LAWYER_NAME = "lawyer_name", "Nome do Advogado"
        PARTY_NAME = "party_name", "Nome da Parte"
        CONTENT_TEXT = "content_text", "Teor da Publicação"
        CASE_NUMBER = "case_number", "Número do Processo"
        OAB = "oab", "OAB"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(IntegrationAccount, on_delete=models.PROTECT, related_name="monitors")
    label = models.CharField("Nome do Monitoramento", max_length=150)
    kind = models.CharField("Tipo de Filtro", max_length=40, choices=Kind.choices)
    value = models.CharField("Termo / Nome Pesquisado", max_length=200)
    oab_uf = models.CharField("UF da OAB", max_length=5, blank=True, null=True)
    tribunal_ids = models.JSONField("Tribunais Selecionados", default=list, blank=True)
    enabled = models.BooleanField("Ativo", default=True)
    contract_status = models.CharField("Status do Contrato", max_length=40, default="PILOT_PENDING")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} ({self.get_kind_display()}: {self.value})"

    @property
    def is_active(self):
        return self.enabled

    @is_active.setter
    def is_active(self, val):
        self.enabled = val


class SyncRun(TenantModel):
    """Audited execution run of a monitoring rule or on-demand search."""
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Enfileirado"
        RUNNING = "RUNNING", "Em Execução"
        COMPLETE = "COMPLETE", "Completo"
        PARTIAL = "PARTIAL", "Parcial"
        FAILED = "FAILED", "Falhou"
        BLOCKED = "BLOCKED", "Bloqueado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(IntegrationAccount, on_delete=models.PROTECT, related_name="runs")
    monitor = models.ForeignKey(MonitoringRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="runs")
    date_from = models.DateField("Data Inicial")
    date_to = models.DateField("Data Final")
    mode = models.CharField("Modo", max_length=20, default="daily", choices=[("daily", "Diário"), ("reconcile", "Reconciliação")])
    status = models.CharField("Status", max_length=20, choices=Status.choices, default=Status.QUEUED)
    page_count = models.PositiveIntegerField("Total de Páginas", default=0)
    item_count = models.PositiveIntegerField("Total de Itens Localizados", default=0)
    coverage_status = models.CharField("Status de Cobertura", max_length=80, default="CRITERIA_CHECKED")
    errors = models.JSONField("Erros e Ocorrências", default=list, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Execução {self.id} · {self.get_status_display()} ({self.item_count} itens)"

    @property
    def created_at(self):
        return self.started_at


class SyncPage(TenantModel):
    """Granular record of paginated fetches for idempotent resumption."""
    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="pages")
    court_code = models.CharField("Tribunal", max_length=30, blank=True)
    cursor_or_page = models.CharField("Página / Cursor", max_length=60)
    items_count = models.PositiveIntegerField("Itens Coletados", default=0)
    payload_hash = models.CharField("Hash do Conteúdo", max_length=64)
    error_message = models.TextField("Erro da Página", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Página {self.cursor_or_page} ({self.items_count} itens)"


class SourceRecord(TenantModel):
    """Raw, tamper-evident record of external communication or event."""
    deployment = models.ForeignKey(SourceDeployment, on_delete=models.SET_NULL, null=True, blank=True)
    source_code = models.CharField("Código da Fonte", max_length=50)
    external_id = models.CharField("ID Externo do Registro", max_length=150)
    payload_hash = models.CharField("Hash SHA-256", max_length=64)
    raw_payload = models.JSONField("Payload Bruto Original", default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "source_code", "external_id"], name="integrations_sourcerecord_uniq"),
        ]

    def __str__(self):
        return f"{self.source_code}:{self.external_id}"


class CourtCommunication(TenantModel):
    """Normalized official judicial notice or publication received."""
    class ReviewStatus(models.TextChoices):
        PENDING_REVIEW = "PENDING_REVIEW", "Aguardando conferência"
        MATCH_CONFIRMED = "MATCH_CONFIRMED", "Vínculo confirmado"
        NOT_RELEVANT = "NOT_RELEVANT", "Descartada"
        NEEDS_INFORMATION = "NEEDS_INFORMATION", "Mais informações necessárias"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_code = models.CharField("Fonte", max_length=50, default="djen")
    external_id = models.CharField("ID Externo / Hash", max_length=150)
    case_number = models.CharField("Número do Processo", max_length=80, blank=True, null=True)
    tribunal = models.CharField("Tribunal", max_length=40, blank=True, null=True)
    body_or_court = models.CharField("Órgão Julgador / Vara", max_length=200, blank=True)
    communication_type = models.CharField("Tipo de Ato", max_length=80, default="Intimação")
    content_text = models.TextField("Teor Original da Publicação", blank=True)
    sanitized_text = models.TextField("Texto Sanitizado", blank=True)
    available_date = models.DateField("Data de Disponibilização", null=True, blank=True)
    publication_date = models.DateField("Data de Publicação", null=True, blank=True)
    recipient_name = models.CharField("Destinatário", max_length=200, blank=True)
    review_status = models.CharField("Situação da Triagem", max_length=40, choices=ReviewStatus.choices, default=ReviewStatus.PENDING_REVIEW)
    deadline_status = models.CharField("Status do Prazo", max_length=40, default="A CONFERIR")
    proposed_due_date = models.DateField("Sugestão de Vencimento", null=True, blank=True)
    matter = models.ForeignKey(Matter, on_delete=models.SET_NULL, null=True, blank=True, related_name="court_communications")
    court_case = models.ForeignKey(CourtCase, on_delete=models.SET_NULL, null=True, blank=True, related_name="court_communications")
    deadline = models.ForeignKey(Deadline, on_delete=models.SET_NULL, null=True, blank=True, related_name="court_communications")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_court_communications")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    sync_run = models.ForeignKey(SyncRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="communications")
    raw_record = models.ForeignKey(SourceRecord, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-available_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "source_code", "external_id"], name="integrations_communication_uniq"),
        ]

    def __str__(self):
        return f"{self.tribunal or 'DJEN'} · {self.case_number or self.external_id} ({self.get_review_status_display()})"

    @property
    def full_content(self):
        return self.content_text

    @full_content.setter
    def full_content(self, value):
        self.content_text = value

    @property
    def communication_date(self):
        return self.available_date or self.publication_date

    @communication_date.setter
    def communication_date(self, value):
        self.available_date = value

    @property
    def court_name(self):
        return self.tribunal or self.body_or_court or "DJEN"

    @court_name.setter
    def court_name(self, value):
        self.tribunal = value

    @property
    def triage_status(self):
        return self.review_status

    @triage_status.setter
    def triage_status(self, value):
        self.review_status = value

    @property
    def matched_matter(self):
        return self.matter

    @matched_matter.setter
    def matched_matter(self, value):
        self.matter = value

    @property
    def matched_case(self):
        return self.court_case

    @matched_case.setter
    def matched_case(self, value):
        self.court_case = value


CourtCommunication.ReviewStatus.PENDING = CourtCommunication.ReviewStatus.PENDING_REVIEW
CourtCommunication.ReviewStatus.CONFIRMED = CourtCommunication.ReviewStatus.MATCH_CONFIRMED
CourtCommunication.ReviewStatus.DISMISSED = CourtCommunication.ReviewStatus.NOT_RELEVANT
CourtCommunication.TriageStatus = CourtCommunication.ReviewStatus


class MonitoringHit(TenantModel):
    """Audit link explaining which criteria matched a communication."""
    communication = models.ForeignKey(CourtCommunication, on_delete=models.CASCADE, related_name="hits")
    monitor = models.ForeignKey(MonitoringRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="hits")
    criteria_matched = models.CharField("Critério Atendido", max_length=40)  # "teor", "parte", "advogado"
    hit_detail = models.TextField("Trecho / Evidência da Coincidência", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Hit: {self.criteria_matched} em {self.communication_id}"


class CommunicationReview(TenantModel):
    """Human review decision for an imported court communication."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    communication = models.ForeignKey(CourtCommunication, on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="communication_reviews")
    decision = models.CharField("Decisão", max_length=40, choices=CourtCommunication.ReviewStatus.choices)
    case = models.ForeignKey(Matter, on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.TextField("Justificativa da Triagem")
    proposed_actions = models.JSONField("Providências Propostas", default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Revisão por {self.reviewer} · {self.decision}"

    @property
    def notes(self):
        return self.reason

    @notes.setter
    def notes(self, value):
        self.reason = value


CommunicationReview.Decision = CourtCommunication.ReviewStatus


class AuthorizationGrant(TenantModel):
    """Guarded, short-lived authorization grant for sensitive acts (e.g. open-official)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    communication = models.ForeignKey(CourtCommunication, on_delete=models.CASCADE, related_name="authorizations")
    operation = models.CharField("Operação Autorizada", max_length=40, default="OPEN_CONTENT")
    account = models.ForeignKey(IntegrationAccount, on_delete=models.PROTECT)
    grantee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    acknowledged_effects = models.BooleanField("Efeitos Jurídicos Reconhecidos", default=False)
    reason = models.TextField("Justificativa")
    reauthentication_reference = models.CharField("Ref. de Reautenticação", max_length=120, blank=True)
    expires_at = models.DateTimeField("Expira em")
    status = models.CharField("Status da Concessão", max_length=20, default="ACTIVE")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self):
        return self.status == "ACTIVE" and self.expires_at > timezone.now()

    def __str__(self):
        return f"Concessão {self.operation} para {self.grantee} ({self.status})"


class ExternalOperation(TenantModel):
    """Audited log of external actions performed with strict idempotency."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation_type = models.CharField("Tipo de Ato", max_length=50)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    account = models.ForeignKey(IntegrationAccount, on_delete=models.PROTECT)
    authorization = models.ForeignKey(AuthorizationGrant, on_delete=models.SET_NULL, null=True, blank=True)
    idempotency_key = models.CharField("Chave de Idempotência", max_length=200)
    status = models.CharField("Status da Operação", max_length=30, default="SUBMITTING")
    official_receipt = models.TextField("Recibo Oficial / Comprovante", blank=True)
    result_summary = models.TextField("Resumo do Resultado", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "idempotency_key"], name="integrations_operation_idemp_uniq"),
        ]

    def __str__(self):
        return f"{self.operation_type} · {self.status} ({self.idempotency_key})"


class WebhookInbox(TenantModel):
    """Durable inbox for signed webhooks with idempotency and replay guards."""
    subscription_id = models.UUIDField("ID da Subscrição")
    external_event_id = models.CharField("ID do Evento Externo", max_length=150)
    payload_hash = models.CharField("Hash SHA-256", max_length=64)
    signature_received = models.CharField("Assinatura HMAC", max_length=64)
    raw_bytes = models.BinaryField("Bytes Originais")
    parsed_payload = models.JSONField("Payload Interpretado", default=dict, blank=True)
    is_duplicate = models.BooleanField("Duplicado", default=False)
    processed = models.BooleanField("Processado", default=False)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "subscription_id", "external_event_id"], name="integrations_webhook_event_uniq"),
        ]

    def __str__(self):
        return f"Webhook {self.external_event_id} ({'Proc' if self.processed else 'Pendente'})"


class DailyReport(TenantModel):
    """Private, versioned Word (.docx) report generated from daily communications."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    base_date = models.DateField("Data-base")
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    format = models.CharField("Formato", max_length=10, default="docx")
    scope_monitors = models.JSONField("Monitores Incluídos", default=list, blank=True)
    summary_counts = models.JSONField("Sumário de Contagens", default=dict, blank=True)
    file_bytes = models.BinaryField("Arquivo Gerado (.docx)")
    file_hash = models.CharField("Hash SHA-256", max_length=64)
    is_partial = models.BooleanField("Relatório Parcial (com falhas)", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Relatório Word {self.base_date} ({'Parcial' if self.is_partial else 'Completo'})"

    @property
    def reference_date(self):
        return self.base_date

    @reference_date.setter
    def reference_date(self, val):
        self.base_date = val

    @property
    def generated_at(self):
        return self.created_at

    @property
    def total_communications(self):
        return self.summary_counts.get("total", 0)

    @property
    def total_matched(self):
        return self.summary_counts.get("confirmed", 0)

    @property
    def total_unmatched(self):
        return self.summary_counts.get("pending", 0) + self.summary_counts.get("dismissed", 0)

    @property
    def summary_data(self):
        return self.summary_counts

    @summary_data.setter
    def summary_data(self, val):
        self.summary_counts = val

    @property
    def filename(self):
        return f"Relatorio_DJEN_{self.base_date.strftime('%Y%m%d')}_{str(self.id)[:8]}.docx"
