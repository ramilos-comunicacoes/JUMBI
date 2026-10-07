from django.conf import settings
from django.db import models

from apps.core.models import Organization


class PracticeArea(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.CharField(max_length=240)
    icon = models.CharField(max_length=48, default="scale")
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class MatterType(models.Model):
    practice_area = models.ForeignKey(PracticeArea, on_delete=models.CASCADE, related_name="matter_types")
    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160)
    description = models.CharField(max_length=240, blank=True)
    workflow_steps = models.JSONField(default=list, blank=True)
    required_documents = models.JSONField(default=list, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["practice_area__sort_order", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["practice_area", "slug"], name="unique_matter_type_per_area"),
        ]

    def __str__(self):
        return f"{self.practice_area.name} · {self.name}"


class Client(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="office_clients")
    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class WorkItem(models.Model):
    class Kind(models.TextChoices):
        TASK = "task", "Tarefa"
        DEADLINE = "deadline", "Prazo"
        HEARING = "hearing", "Audiência"
        APPOINTMENT = "appointment", "Compromisso"
        FOLLOW_UP = "follow_up", "Acompanhamento"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"
        URGENT = "urgent", "Urgente"

    class Status(models.TextChoices):
        TODO = "todo", "A fazer"
        IN_PROGRESS = "in_progress", "Em andamento"
        DONE = "done", "Concluida"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="office_work_items")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="work_items")
    case = models.ForeignKey("LegalCase", on_delete=models.SET_NULL, null=True, blank=True, related_name="work_items")
    title = models.CharField(max_length=180)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.TASK)
    priority = models.CharField(max_length=12, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    due_date = models.DateField(null=True, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_work_items")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "due_date", "title"]
        indexes = [
            models.Index(
                fields=["organization", "status", "due_date"],
                name="office_task_queue_idx",
            ),
            models.Index(
                fields=["organization", "case"],
                name="office_task_case_idx",
            ),
        ]

    def __str__(self):
        return self.title


class StaffMember(models.Model):
    class Role(models.TextChoices):
        LAWYER = "lawyer", "Advogado"
        PARALEGAL = "paralegal", "Assistente juridico"
        FINANCE = "finance", "Financeiro"
        ADMIN = "admin", "Administrativo"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="office_staff")
    name = models.CharField(max_length=160)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ADMIN)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LegalCase(models.Model):
    class Nature(models.TextChoices):
        JUDICIAL = "judicial", "Judicial"
        ADMINISTRATIVE = "administrative", "Administrativo"
        EXTRAJUDICIAL = "extrajudicial", "Extrajudicial"
        ADVISORY = "advisory", "Consultivo"

    class Priority(models.TextChoices):
        LOW = "low", "Baixa"
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"
        URGENT = "urgent", "Urgente"

    class Stage(models.TextChoices):
        INTAKE = "intake", "Triagem"
        DOCUMENTS = "documents", "Coleta documental"
        ANALYSIS = "analysis", "Análise jurídica"
        DRAFTING = "drafting", "Elaboração"
        FILING = "filing", "Protocolo / depósito"
        IN_PROGRESS = "in_progress", "Em andamento"
        HEARING = "hearing", "Audiência / sessão"
        NEGOTIATION = "negotiation", "Negociação"
        ENFORCEMENT = "enforcement", "Cumprimento / execução"
        WAITING = "waiting", "Aguardando terceiro"
        CLOSED = "closed", "Encerrado"

    class Status(models.TextChoices):
        INTAKE = "intake", "Triagem"
        ACTIVE = "active", "Ativo"
        WAITING = "waiting", "Aguardando"
        CLOSED = "closed", "Encerrado"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="office_cases")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="cases")
    practice_area = models.ForeignKey(
        PracticeArea, on_delete=models.SET_NULL, null=True, blank=True, related_name="cases"
    )
    matter_type = models.ForeignKey(
        MatterType, on_delete=models.SET_NULL, null=True, blank=True, related_name="cases"
    )
    title = models.CharField(max_length=180)
    case_number = models.CharField(max_length=80, blank=True)
    court = models.CharField(max_length=160, blank=True)
    opposing_party = models.CharField(max_length=180, blank=True)
    description = models.TextField(blank=True)
    nature = models.CharField(max_length=20, choices=Nature.choices, default=Nature.JUDICIAL)
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.INTAKE)
    priority = models.CharField(max_length=12, choices=Priority.choices, default=Priority.NORMAL)
    confidential = models.BooleanField(default=False)
    custom_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INTAKE)
    responsible = models.ForeignKey(StaffMember, on_delete=models.SET_NULL, null=True, blank=True, related_name="cases")
    next_deadline = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "next_deadline", "title"]
        indexes = [
            models.Index(
                fields=["organization", "confidential", "status"],
                name="office_case_vis_status_idx",
            ),
            models.Index(
                fields=["organization", "next_deadline"],
                name="office_case_deadline_idx",
            ),
        ]

    def __str__(self):
        return self.title


class LegalDocument(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="office_documents")
    case = models.ForeignKey(LegalCase, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    title = models.CharField(max_length=180)
    document_type = models.CharField(max_length=80, blank=True)
    file = models.FileField(upload_to="office/documents/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class OfficeFinanceEntry(models.Model):
    class Kind(models.TextChoices):
        REVENUE = "revenue", "Receita"
        EXPENSE = "expense", "Despesa"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="office_finance_entries")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="finance_entries")
    case = models.ForeignKey(LegalCase, on_delete=models.SET_NULL, null=True, blank=True, related_name="finance_entries")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    description = models.CharField(max_length=180)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["paid", "due_date", "description"]

    def __str__(self):
        return self.description


class OfficePurchase(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="office_purchases")
    supplier_name = models.CharField(max_length=160)
    item = models.CharField(max_length=180)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    purchased_at = models.DateField(null=True, blank=True)
    paid = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["paid", "-created_at"]

    def __str__(self):
        return self.item
