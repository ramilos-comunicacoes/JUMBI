from decimal import Decimal

from django.db import models

from apps.core.models import Organization


class Farm(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="farms")
    name = models.CharField(max_length=180)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    total_area_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Field(models.Model):
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="fields")
    name = models.CharField(max_length=160)
    crop = models.CharField(max_length=100, blank=True)
    area_hectares = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["farm__name", "name"]

    def __str__(self):
        return f"{self.farm} - {self.name}"


class StaffMember(models.Model):
    class Role(models.TextChoices):
        MANAGER = "manager", "Gestor rural"
        AGRONOMIST = "agronomist", "Agronomo"
        OPERATOR = "operator", "Operador"
        FINANCE = "finance", "Financeiro"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="agro_staff")
    name = models.CharField(max_length=160)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OPERATOR)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    farm = models.ForeignKey(Farm, on_delete=models.SET_NULL, null=True, blank=True, related_name="staff")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Supplier(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="agro_suppliers")
    name = models.CharField(max_length=180)
    document = models.CharField(max_length=18, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    class Unit(models.TextChoices):
        UN = "UN", "Unidade"
        KG = "KG", "Kg"
        L = "L", "Litro"
        BAG = "BAG", "Saco"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="agro_inventory")
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=80, blank=True)
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.UN)
    stock = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    minimum_stock = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    @property
    def needs_restock(self):
        return self.minimum_stock > 0 and self.stock <= self.minimum_stock

    def __str__(self):
        return self.name


class FarmOperation(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planejada"
        RUNNING = "running", "Em execucao"
        REVIEW = "review", "Em validacao"
        DONE = "done", "Concluida"

    class Kind(models.TextChoices):
        PLANTING = "planting", "Plantio"
        SPRAYING = "spraying", "Pulverizacao"
        HARVEST = "harvest", "Colheita"
        SOIL = "soil", "Solo"
        MAINTENANCE = "maintenance", "Manutencao"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="agro_operations")
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="operations")
    field = models.ForeignKey(Field, on_delete=models.SET_NULL, null=True, blank=True, related_name="operations")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PLANTING)
    title = models.CharField(max_length=180)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    scheduled_date = models.DateField(null=True, blank=True)
    responsible = models.ForeignKey(StaffMember, on_delete=models.SET_NULL, null=True, blank=True, related_name="operations")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "scheduled_date", "title"]

    def __str__(self):
        return self.title


class AgroFinanceEntry(models.Model):
    class Kind(models.TextChoices):
        REVENUE = "revenue", "Receita"
        EXPENSE = "expense", "Despesa"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="agro_finance_entries")
    farm = models.ForeignKey(Farm, on_delete=models.SET_NULL, null=True, blank=True, related_name="finance_entries")
    field = models.ForeignKey(Field, on_delete=models.SET_NULL, null=True, blank=True, related_name="finance_entries")
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


class AgroPurchase(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="agro_purchases")
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchases")
    item = models.ForeignKey(InventoryItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="purchases")
    description = models.CharField(max_length=180)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"))
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    purchased_at = models.DateField(null=True, blank=True)
    paid = models.BooleanField(default=False)
    received = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received", "-created_at"]

    def __str__(self):
        return self.description
