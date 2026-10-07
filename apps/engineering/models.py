from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import Organization


class OrganizationScopedQuerySet(models.QuerySet):
    def for_membership(self, membership):
        if membership is None:
            return self.none()
        return self.filter(organization=membership.organization)


class Supplier(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="engineering_suppliers")
    name = models.CharField(max_length=180)
    document = models.CharField(max_length=18, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Project(models.Model):
    class Status(models.TextChoices):
        PLANNING = "planning", "Planejamento"
        ACTIVE = "active", "Em execucao"
        COMPLETED = "completed", "Concluido"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="engineering_projects")
    name = models.CharField(max_length=180)
    client_name = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    budget = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrganizationScopedQuerySet.as_manager()

    class Meta:
        ordering = ["status", "name"]

    def __str__(self):
        return self.name


class ProjectTask(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "A fazer"
        DOING = "doing", "Em progresso"
        REVIEW = "review", "Aguardando aprovacao"
        DONE = "done", "Concluida"

    class Priority(models.TextChoices):
        LOW = "low", "Baixa"
        NORMAL = "normal", "Normal"
        HIGH = "high", "Alta"
        CRITICAL = "critical", "Critica"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="engineering_tasks")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO, db_index=True)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    due_date = models.DateField(null=True, blank=True, db_index=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="engineering_tasks")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_engineering_tasks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrganizationScopedQuerySet.as_manager()

    class Meta:
        ordering = ["status", "due_date", "-priority", "title"]

    def __str__(self):
        return self.title


class ProjectEvidence(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="engineering_evidences")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="evidences")
    task = models.ForeignKey(ProjectTask, on_delete=models.SET_NULL, null=True, blank=True, related_name="evidences")
    title = models.CharField(max_length=180)
    notes = models.TextField(blank=True)
    file = models.FileField(upload_to="engineering/evidences/", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="engineering_evidences")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Employee(models.Model):
    class Role(models.TextChoices):
        ENGINEER = "engineer", "Engenheiro"
        ARCHITECT = "architect", "Arquiteto"
        FOREMAN = "foreman", "Mestre de obras"
        BUYER = "buyer", "Compras"
        FINANCE = "finance", "Financeiro"
        ASSISTANT = "assistant", "Assistente"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="engineering_employees")
    name = models.CharField(max_length=160)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ASSISTANT)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="employees")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class FinanceEntry(models.Model):
    class Kind(models.TextChoices):
        REVENUE = "revenue", "Receita"
        EXPENSE = "expense", "Despesa"

    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        PAID = "paid", "Pago"
        OVERDUE = "overdue", "Vencido"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="engineering_finance_entries")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="finance_entries")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    description = models.CharField(max_length=180)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedQuerySet.as_manager()

    class Meta:
        ordering = ["status", "due_date", "description"]

    def __str__(self):
        return self.description


class Purchase(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Solicitada"
        QUOTING = "quoting", "Cotando"
        APPROVED = "approved", "Aprovada"
        RECEIVED = "received", "Recebida"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="engineering_purchases")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchases")
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchases")
    item = models.CharField(max_length=180)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"))
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    requested_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedQuerySet.as_manager()

    class Meta:
        ordering = ["status", "-created_at"]

    def __str__(self):
        return self.item
