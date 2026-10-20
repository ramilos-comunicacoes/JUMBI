import hashlib
from decimal import Decimal
from django.db import models
from django.utils import timezone
from apps.core.models import Membership, Organization


class WorkSchedule(models.Model):
    """
    Jornada de Trabalho da empresa (ex: Padrão 40h, 44h, Estágio 30h, 12x36).
    Define os horários esperados de entrada e saída por dia da semana e a tolerância.
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="work_schedules", verbose_name="Escritório"
    )
    name = models.CharField("Nome da jornada", max_length=120)
    description = models.TextField("Descrição / Observações", blank=True, default="")
    daily_expected_hours = models.DecimalField(
        "Horas diárias previstas", max_digits=4, decimal_places=2, default=Decimal("8.00")
    )
    tolerance_minutes = models.PositiveIntegerField(
        "Tolerância em minutos (CLT)", default=10, help_text="Variação permitida de horário sem gerar atraso ou hora extra."
    )
    # Dicionário com dias 0 (segunda) a 6 (domingo)
    schedule_grid = models.JSONField(
        "Grade semanal de horários",
        default=dict,
        blank=True,
        help_text="Define horários de entrada e saída de cada dia da semana."
    )
    is_default = models.BooleanField("Jornada padrão do escritório", default=False)
    is_active = models.BooleanField("Ativa", default=True)
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    updated_at = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Jornada de Trabalho"
        verbose_name_plural = "Jornadas de Trabalho"
        ordering = ["-is_default", "name"]

    def __str__(self):
        return f"{self.name} ({self.daily_expected_hours}h/dia)"

    @classmethod
    def get_default_grid(cls):
        """Retorna grade padrão 40h (Seg a Sex 08:00 - 12:00 / 13:00 - 17:00, Sáb/Dom folga)."""
        return {
            "0": {"active": True, "entry_1": "08:00", "exit_1": "12:00", "entry_2": "13:00", "exit_2": "17:00", "expected_hours": 8.0},
            "1": {"active": True, "entry_1": "08:00", "exit_1": "12:00", "entry_2": "13:00", "exit_2": "17:00", "expected_hours": 8.0},
            "2": {"active": True, "entry_1": "08:00", "exit_1": "12:00", "entry_2": "13:00", "exit_2": "17:00", "expected_hours": 8.0},
            "3": {"active": True, "entry_1": "08:00", "exit_1": "12:00", "entry_2": "13:00", "exit_2": "17:00", "expected_hours": 8.0},
            "4": {"active": True, "entry_1": "08:00", "exit_1": "12:00", "entry_2": "13:00", "exit_2": "17:00", "expected_hours": 8.0},
            "5": {"active": False, "is_day_off": True, "expected_hours": 0.0},
            "6": {"active": False, "is_day_off": True, "expected_hours": 0.0},
        }

    def save(self, *args, **kwargs):
        if not self.schedule_grid:
            self.schedule_grid = self.get_default_grid()
        if self.is_default:
            WorkSchedule.objects.filter(organization=self.organization, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class EmployeeSchedule(models.Model):
    """Vínculo da jornada com o colaborador/membro do escritório."""
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="employee_schedules"
    )
    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="ponto_schedule", verbose_name="Colaborador"
    )
    schedule = models.ForeignKey(
        WorkSchedule, on_delete=models.PROTECT, related_name="employees", verbose_name="Jornada"
    )
    require_face_match = models.BooleanField(
        "Exigir validação facial (Google MediaPipe)", default=True
    )
    allow_remote_clock = models.BooleanField(
        "Permitir bater ponto externo / home office", default=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Jornada do Colaborador"
        verbose_name_plural = "Jornadas dos Colaboradores"

    def __str__(self):
        return f"{self.membership.user.get_full_name() or self.membership.user.email} -> {self.schedule.name}"


class HolidayOrDayOff(models.Model):
    """Calendário de Feriados, Folgas Coletivas e Dias Não Úteis da Empresa."""
    class Kind(models.TextChoices):
        NATIONAL = "national", "Feriado Nacional"
        STATE = "state", "Feriado Estadual"
        MUNICIPAL = "municipal", "Feriado Municipal"
        OPTIONAL = "optional", "Ponto Facultativo"
        COMPANY_OFF = "company_off", "Folga Coletiva / Recesso da Empresa"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="holidays"
    )
    date = models.DateField("Data")
    name = models.CharField("Nome do feriado / folga", max_length=140)
    kind = models.CharField("Tipo", max_length=20, choices=Kind.choices, default=Kind.NATIONAL)
    repeats_yearly = models.BooleanField("Repete anualmente", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Feriado ou Folga"
        verbose_name_plural = "Feriados e Folgas"
        ordering = ["date"]
        unique_together = ("organization", "date", "name")

    def __str__(self):
        return f"{self.date.strftime('%d/%m/%Y')} - {self.name} ({self.get_kind_display()})"


class TimeRecord(models.Model):
    """
    Registro individual de batida de ponto eletrônico.
    Inclui hash SHA-256 de integridade e metadados biométricos (Google MediaPipe).
    """
    class RecordType(models.TextChoices):
        ENTRY_1 = "entry_1", "Entrada"
        EXIT_1 = "exit_1", "Saída para Intervalo"
        ENTRY_2 = "entry_2", "Retorno do Intervalo"
        EXIT_2 = "exit_2", "Saída / Fim de Expediente"
        ENTRY_EXTRA = "entry_extra", "Entrada Extra"
        EXIT_EXTRA = "exit_extra", "Saída Extra"

    class Source(models.TextChoices):
        FACIAL_WEBCAM = "webcam_face", "Biometria Facial (Google MediaPipe Web)"
        FACIAL_MOBILE = "mobile_face", "Biometria Facial Mobile"
        MANUAL_ADMIN = "manual_admin", "Inclusão Manual pelo Gestor"
        SYSTEM_ADJUSTED = "system", "Ajuste Aprovado por Solicitação"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="time_records"
    )
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="time_records", verbose_name="Colaborador"
    )
    timestamp = models.DateTimeField("Data e Hora exata", default=timezone.now)
    recorded_date = models.DateField("Data da jornada", default=timezone.now)
    record_type = models.CharField("Tipo de batida", max_length=20, choices=RecordType.choices)
    source = models.CharField("Origem", max_length=20, choices=Source.choices, default=Source.FACIAL_WEBCAM)

    # Dados biométricos (Google MediaPipe)
    face_detected = models.BooleanField("Rosto detectado com sucesso", default=True)
    face_confidence = models.FloatField("Confiança da detecção facial", default=0.0)
    face_landmarks_count = models.PositiveIntegerField("Pontos faciais mapeados", default=0)
    photo_snapshot = models.TextField("Foto da batida (Base64)", blank=True, default="")

    # Geolocalização & Dispositivo
    latitude = models.FloatField("Latitude", null=True, blank=True)
    longitude = models.FloatField("Longitude", null=True, blank=True)
    location_accuracy = models.FloatField("Precisão GPS (m)", null=True, blank=True)
    location_address = models.CharField("Local aproximado", max_length=255, blank=True, default="")
    ip_address = models.GenericIPAddressField("Endereço IP", null=True, blank=True)
    user_agent = models.CharField("Navegador / Dispositivo", max_length=255, blank=True, default="")

    # Hash de integridade criptográfica (Portaria 671 / MTP)
    hash_sha256 = models.CharField("Hash de Autenticidade SHA-256", max_length=64, blank=True, default="")

    # Auditoria de edição / ajuste manual
    is_manually_adjusted = models.BooleanField("Registro ajustado / manual", default=False)
    adjustment_reason = models.TextField("Justificativa legal do ajuste", blank=True, default="")
    adjusted_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="adjusted_time_records",
        verbose_name="Ajustado por"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Batida de Ponto"
        verbose_name_plural = "Batidas de Ponto"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["organization", "membership", "recorded_date"]),
            models.Index(fields=["organization", "timestamp"]),
        ]

    def __str__(self):
        user_name = self.membership.user.get_full_name() or self.membership.user.email
        return f"{self.timestamp.strftime('%d/%m/%Y %H:%M:%S')} - {self.get_record_type_display()} ({user_name})"

    def calculate_hash(self):
        """Gera hash SHA-256 inviolável dos dados da batida para comprovação legal."""
        raw = f"{self.organization_id}|{self.membership_id}|{self.timestamp.isoformat()}|{self.record_type}|{self.latitude}|{self.longitude}|{self.ip_address}|{self.face_confidence}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        if not self.recorded_date:
            self.recorded_date = self.timestamp.date()
        if not self.hash_sha256:
            self.hash_sha256 = self.calculate_hash()
        super().save(*args, **kwargs)


class TimeAdjustmentRequest(models.Model):
    """
    Solicitação de ajuste de ponto, atestado médico ou justificativa enviada pelo funcionário
    para aprovação do Gestor ou Administrador (estilo IfPonto / Fractal).
    """
    class RequestType(models.TextChoices):
        MISSING_PUNCH = "missing_punch", "Esquecimento de Batida"
        MEDICAL_LEAVE = "medical_leave", "Atestado Médico / Licença Saúde"
        EXTERNAL_DUTY = "external_duty", "Serviço Externo / Audiência"
        DELAY_JUSTIFY = "delay_justify", "Justificativa de Atraso"
        DAY_OFF_SWAP = "day_off_swap", "Compensação / Troca de Folga"

    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando Análise"
        APPROVED = "approved", "Aprovada"
        REJECTED = "rejected", "Recusada"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="adjustment_requests"
    )
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="time_adjustment_requests", verbose_name="Colaborador"
    )
    date = models.DateField("Data do ponto")
    request_type = models.CharField("Tipo de solicitação", max_length=25, choices=RequestType.choices)
    suggested_time = models.TimeField("Horário sugerido", null=True, blank=True)
    suggested_record_type = models.CharField(
        "Tipo de batida correspondente", max_length=20, choices=TimeRecord.RecordType.choices, blank=True, default=""
    )
    reason = models.TextField("Motivo / Justificativa detalhada")
    attachment = models.FileField(
        "Comprovante ou Atestado (PDF/Imagem)", upload_to="ponto/atestados/%Y/%m/", null=True, blank=True
    )
    attachment_base64 = models.TextField("Comprovante em Base64", blank=True, default="")
    status = models.CharField("Situação", max_length=15, choices=Status.choices, default=Status.PENDING)

    reviewed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_adjustments",
        verbose_name="Analisado por"
    )
    review_notes = models.TextField("Parecer do gestor", blank=True, default="")
    reviewed_at = models.DateTimeField("Data da decisão", null=True, blank=True)
    created_at = models.DateTimeField("Solicitado em", auto_now_add=True)

    class Meta:
        verbose_name = "Solicitação de Ajuste / Atestado"
        verbose_name_plural = "Solicitações de Ajuste / Atestados"
        ordering = ["-created_at"]

    def __str__(self):
        user_name = self.membership.user.get_full_name() or self.membership.user.email
        return f"{self.date.strftime('%d/%m/%Y')} - {self.get_request_type_display()} por {user_name} [{self.get_status_display()}]"
