from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone


class MarketingChannel(models.TextChoices):
    META_ADS = "meta_ads", "Meta Ads (Instagram / Facebook)"
    GOOGLE_ADS = "google_ads", "Google Ads / Pesquisa"
    INDICACAO = "indicacao", "Indicação de Clientes / Parceiros"
    WHATSAPP = "whatsapp", "WhatsApp / Prospecção Ativa"
    ORGANICO = "organico", "Orgânico / Redes Sociais / SEO"
    EVENTOS = "eventos", "Eventos / Palestras"
    OUTROS = "outros", "Outros Canais"


class CampaignObjective(models.TextChoices):
    LEADS = "leads", "Captação de Novos Leads"
    PREVIDENCIARIO = "previdenciario", "Previdenciário (Aposentadoria / BPC)"
    TRABALHISTA = "trabalhista", "Trabalhista & Acidentes"
    REVISIONAL = "revisional", "Cível & Revisional de Contratos"
    INSTITUCIONAL = "institucional", "Branding & Reconhecimento de Marca"
    OUTROS = "outros", "Outro Objetivo"


class CampaignStatus(models.TextChoices):
    PLANEJADA = "planejada", "Planejada"
    ATIVA = "ativa", "Ativa"
    PAUSADA = "pausada", "Pausada"
    CONCLUIDA = "concluida", "Concluída"
    CANCELADA = "cancelada", "Cancelada"


class LeadStage(models.TextChoices):
    NOVO = "novo", "Novo Lead"
    CONTATO = "contato", "Contato Realizado"
    QUALIFICADO = "qualificado", "Qualificado / Reunião Agendada"
    PROPOSTA = "proposta", "Proposta de Honorários Enviada"
    CONVERTIDO = "convertido", "Fechou Contrato (Cliente Ativo)"
    PERDIDO = "perdido", "Perdido / Desqualificado"


class Campaign(models.Model):
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.CASCADE,
        related_name="marketing_campaigns",
    )
    name = models.CharField("Nome da Campanha", max_length=200)
    channel = models.CharField("Canal de Aquisição", max_length=50, choices=MarketingChannel.choices, default=MarketingChannel.META_ADS)
    objective = models.CharField("Objetivo", max_length=50, choices=CampaignObjective.choices, default=CampaignObjective.PREVIDENCIARIO)
    budget = models.DecimalField("Orçamento Previsto (R$)", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    spent = models.DecimalField("Investimento Realizado (R$)", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField("Status", max_length=20, choices=CampaignStatus.choices, default=CampaignStatus.ATIVA)
    start_date = models.DateField("Data de Início", default=timezone.now)
    end_date = models.DateField("Data de Término", null=True, blank=True)
    
    # UTM parameters
    utm_source = models.CharField("UTM Source", max_length=100, blank=True, help_text="Ex: instagram, google, facebook")
    utm_medium = models.CharField("UTM Medium", max_length=100, blank=True, help_text="Ex: cpc, stories, feed, bio")
    utm_campaign = models.CharField("UTM Campaign", max_length=100, blank=True, help_text="Ex: previdenciario_inss_2026")
    utm_content = models.CharField("UTM Content", max_length=100, blank=True, help_text="Ex: video_aposentadoria_idade")
    
    target_audience = models.TextField("Público-Alvo", blank=True)
    notes = models.TextField("Observações Estratégicas", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_campaigns",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-created_at"]
        verbose_name = "Campanha de Marketing"
        verbose_name_plural = "Campanhas de Marketing"

    def __str__(self):
        return f"{self.name} ({self.get_channel_display()})"

    @property
    def total_leads_count(self):
        return self.leads.count()

    @property
    def converted_leads_count(self):
        return self.leads.filter(stage=LeadStage.CONVERTIDO).count()

    @property
    def conversion_rate(self):
        total = self.total_leads_count
        if not total:
            return Decimal("0.0")
        return round(Decimal(self.converted_leads_count) / Decimal(total) * Decimal("100"), 1)

    @property
    def cost_per_lead(self):
        total = self.total_leads_count
        if not total or not self.spent:
            return Decimal("0.00")
        return round(self.spent / Decimal(total), 2)

    @property
    def cost_per_acquisition(self):
        conv = self.converted_leads_count
        if not conv or not self.spent:
            return Decimal("0.00")
        return round(self.spent / Decimal(conv), 2)

    @property
    def total_revenue(self):
        return sum((l.closed_value or Decimal("0.00")) for l in self.leads.filter(stage=LeadStage.CONVERTIDO)) or Decimal("0.00")

    @property
    def roas(self):
        if not self.spent or self.spent == 0:
            return Decimal("0.0")
        return round(self.total_revenue / self.spent, 2)


class Lead(models.Model):
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.CASCADE,
        related_name="marketing_leads",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    name = models.CharField("Nome Completo / Interessado", max_length=255)
    phone = models.CharField("WhatsApp / Telefone", max_length=50)
    email = models.EmailField("E-mail", blank=True)
    channel = models.CharField("Canal de Origem", max_length=50, choices=MarketingChannel.choices, default=MarketingChannel.META_ADS)
    legal_area = models.CharField("Área de Interesse", max_length=60, default="previdenciario", help_text="Ex: previdenciario, trabalhista, civel, etc.")
    stage = models.CharField("Etapa do Funil", max_length=30, choices=LeadStage.choices, default=LeadStage.NOVO)
    
    estimated_value = models.DecimalField("Honorários Estimados (R$)", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    closed_value = models.DecimalField("Valor Contratado (R$)", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField("Histórico & Anotações de Atendimento", blank=True)
    loss_reason = models.CharField("Motivo de Perda / Desqualificação", max_length=255, blank=True)
    
    # Conversions
    converted_contact = models.ForeignKey(
        "legal.Contact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketing_leads",
        verbose_name="Cliente Convertido",
    )
    converted_matter = models.ForeignKey(
        "legal.Matter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketing_leads",
        verbose_name="Pasta Jurídica Gerada",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads",
        verbose_name="Responsável Comercial",
    )
    
    first_contact_at = models.DateTimeField("Data do 1º Contato", null=True, blank=True)
    converted_at = models.DateTimeField("Data da Conversão", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Lead de Marketing"
        verbose_name_plural = "Leads de Marketing"

    def __str__(self):
        return f"{self.name} · {self.get_stage_display()} ({self.phone})"


class MarketingExpense(models.Model):
    class ExpenseCategory(models.TextChoices):
        ANUNCIOS = "anuncios", "Tráfego Pago / Anúncios"
        AGENCIA = "agencia", "Agência / Assessoria"
        SOFTWARE = "software", "Ferramentas / Software / CRM"
        CRIACAO = "criacao", "Design / Vídeo / Audiovisual"
        EVENTOS = "eventos", "Eventos / Palestras / Brindes"
        OUTROS = "outros", "Outros Custos de Marketing"

    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.CASCADE,
        related_name="marketing_expenses",
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
    )
    title = models.CharField("Descrição do Custo", max_length=255)
    category = models.CharField("Categoria", max_length=40, choices=ExpenseCategory.choices, default=ExpenseCategory.ANUNCIOS)
    amount = models.DecimalField("Valor (R$)", max_digits=12, decimal_places=2)
    date = models.DateField("Data da Despesa", default=timezone.now)
    notes = models.TextField("Observações", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "Despesa de Marketing"
        verbose_name_plural = "Despesas de Marketing"

    def __str__(self):
        return f"{self.title} - R$ {self.amount}"
