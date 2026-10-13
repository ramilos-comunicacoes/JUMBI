"""Office supplies and assets; all quantity changes have an immutable ledger."""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from apps.legal.models import ImmutableTenantModel, TenantModel


class CatalogModel(TenantModel):
    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise ValidationError("Preserve o histórico. Desative o cadastro quando necessário.")


class Category(CatalogModel):
    name = models.CharField("Categoria", max_length=100)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="inventory_category_name_unique")]

    def __str__(self):
        return self.name


class Supplier(CatalogModel):
    name = models.CharField("Fornecedor", max_length=180)
    document = models.CharField("CPF / CNPJ", max_length=30, blank=True)
    phone = models.CharField("Telefone", max_length=40, blank=True)
    email = models.EmailField("E-mail", blank=True)
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name


class Product(CatalogModel):
    class Unit(models.TextChoices):
        UNIT = "un", "Unidade"
        KILOGRAM = "kg", "Quilograma"
        LITRE = "l", "Litro"
        PACKAGE = "pct", "Pacote"
        BOX = "cx", "Caixa"
        METRE = "m", "Metro"

    code = models.CharField("Código interno", max_length=40)
    name = models.CharField("Material", max_length=180)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True, blank=True, related_name="products", verbose_name="Categoria")
    unit = models.CharField("Unidade", max_length=3, choices=Unit.choices, default=Unit.UNIT)
    location = models.CharField("Local de armazenamento", max_length=150, blank=True)
    minimum_stock = models.DecimalField("Estoque mínimo", max_digits=12, decimal_places=3, default=Decimal("0"))
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="inventory_product_code_unique"),
            models.CheckConstraint(condition=Q(minimum_stock__gte=0), name="inventory_minimum_nonnegative"),
        ]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def current_stock(self):
        if hasattr(self, "stock_total"):
            return self.stock_total or Decimal("0")
        return self.lots.aggregate(total=Sum("quantity"))["total"] or Decimal("0")

    @property
    def is_low_stock(self):
        return self.is_active and self.current_stock <= self.minimum_stock

    def clean(self):
        super().clean()
        if self.minimum_stock is not None and self.minimum_stock < 0:
            raise ValidationError({"minimum_stock": "O mínimo não pode ser negativo."})
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            if old and old.unit != self.unit and self.lots.exists():
                raise ValidationError({"unit": "A unidade deve ser preservada após a criação de lotes. Cadastre outro material."})


class StockLotQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Altere saldos pelos serviços de movimentação.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Crie lotes pelos serviços de movimentação.")

    def delete(self):
        raise ValidationError("Preserve o histórico dos lotes.")


class StockLot(TenantModel):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="lots", verbose_name="Material")
    code = models.CharField("Lote", max_length=80)
    expires_on = models.DateField("Validade", null=True, blank=True)
    quantity = models.DecimalField("Saldo", max_digits=12, decimal_places=3, default=Decimal("0"), editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = StockLotQuerySet.as_manager()

    class Meta:
        ordering = ["expires_on", "code", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "product", "code"], name="inventory_lot_code_unique"),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="inventory_lot_quantity_nonnegative"),
        ]

    def __str__(self):
        return f"{self.product.name} · {self.code} · {self.quantity} {self.product.unit}"

    def save(self, *args, **kwargs):
        if not getattr(self, "_inventory_transition", False):
            raise ValidationError("Crie e altere lotes pelos serviços de movimentação.")
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and (previous.product_id != self.product_id or previous.code != self.code or previous.expires_on != self.expires_on):
                raise ValidationError("A identificação e a validade do lote devem ser preservadas.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Preserve o histórico dos lotes.")


class Purchase(TenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Aguardando recebimento"
        RECEIVED = "received", "Recebida"
        CANCELLED = "cancelled", "Cancelada"

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="purchases", verbose_name="Fornecedor")
    reference = models.CharField("Referência / nota fiscal", max_length=100, blank=True)
    notes = models.TextField("Observações", max_length=3000, blank=True, validators=[MaxLengthValidator(3000)])
    purchased_on = models.DateField("Data da compra", default=timezone.localdate)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inventory_purchases")
    created_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="inventory_received_purchases")
    cancellation_reason = models.CharField(max_length=500, blank=True)
    operation_key = models.UUIDField(default=uuid.uuid4, editable=False)
    request_hash = models.CharField(max_length=64, editable=False)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "operation_key"], name="inventory_purchase_operation_unique")]

    @property
    def total(self):
        return sum((item.subtotal for item in self.items.all()), Decimal("0.00"))

    def __str__(self):
        return self.reference or f"Compra #{self.pk}"

    def save(self, *args, **kwargs):
        if not getattr(self, "_inventory_transition", False):
            raise ValidationError("Crie e altere compras pelos serviços de estoque.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Cancele a compra sem apagar o histórico.")


class PurchaseItem(ImmutableTenantModel):
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="purchase_items", verbose_name="Material")
    quantity = models.DecimalField("Quantidade", max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField("Custo unitário (R$)", max_digits=12, decimal_places=2)
    lot_code = models.CharField("Lote no recebimento", max_length=80)
    expires_on = models.DateField("Validade", null=True, blank=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="inventory_purchase_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="inventory_purchase_cost_nonnegative"),
        ]

    @property
    def subtotal(self):
        from decimal import ROUND_HALF_UP
        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def clean(self):
        super().clean()
        if self.purchase_id and self.purchase.status != Purchase.Status.DRAFT:
            raise ValidationError("Os itens só podem ser cadastrados antes do recebimento da compra.")
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError({"quantity": "Informe uma quantidade positiva."})
        if self.unit_cost is not None and self.unit_cost < 0:
            raise ValidationError({"unit_cost": "O custo não pode ser negativo."})


class Movement(ImmutableTenantModel):
    class Kind(models.TextChoices):
        ENTRY = "entry", "Entrada"
        CONSUMPTION = "consumption", "Consumo"
        LOSS = "loss", "Perda"
        COUNT = "count", "Contagem física"
        REVERSAL = "reversal", "Estorno"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField("Operação", max_length=12, choices=Kind.choices)
    quantity = models.DecimalField("Variação", max_digits=12, decimal_places=3)
    balance_after = models.DecimalField("Saldo do lote após operação", max_digits=12, decimal_places=3)
    reason = models.CharField("Motivo", max_length=500)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inventory_movements")
    created_at = models.DateTimeField(auto_now_add=True)
    operation_key = models.UUIDField(default=uuid.uuid4, editable=False)
    request_hash = models.CharField(max_length=64, editable=False)
    reversal_of = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal")
    purchase_item = models.OneToOneField(PurchaseItem, on_delete=models.PROTECT, null=True, blank=True, related_name="movement")

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "operation_key"], name="inventory_movement_operation_unique"),
            models.CheckConstraint(condition=Q(balance_after__gte=0), name="inventory_movement_balance_nonnegative"),
        ]

    def clean(self):
        super().clean()
        if not self.reason or not self.reason.strip():
            raise ValidationError({"reason": "Informe o motivo da movimentação."})
        if self.lot_id and self.lot.product_id != self.product_id:
            raise ValidationError("O lote precisa pertencer ao material movimentado.")
        if self.quantity is not None:
            if self.kind == self.Kind.ENTRY and self.quantity <= 0:
                raise ValidationError("Uma entrada precisa ter quantidade positiva.")
            if self.kind in {self.Kind.CONSUMPTION, self.Kind.LOSS} and self.quantity >= 0:
                raise ValidationError("Uma saída precisa reduzir o saldo.")
        if self.reversal_of_id:
            origin = self.reversal_of
            if self.kind != self.Kind.REVERSAL or origin.kind == self.Kind.REVERSAL or origin.product_id != self.product_id or origin.lot_id != self.lot_id or self.quantity != -origin.quantity:
                raise ValidationError("O estorno deve compensar exatamente a movimentação de origem.")
        elif self.kind == self.Kind.REVERSAL:
            raise ValidationError("Indique a movimentação a estornar.")
        if self.purchase_item_id and (self.kind != self.Kind.ENTRY or self.purchase_item.product_id != self.product_id or self.purchase_item.quantity != self.quantity):
            raise ValidationError("A entrada precisa corresponder ao item comprado.")

    def save(self, *args, **kwargs):
        if not getattr(self, "_inventory_transition", False):
            raise ValidationError("Registre movimentações pelos serviços de estoque.")
        return super().save(*args, **kwargs)


class Asset(CatalogModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Disponível"
        IN_USE = "in_use", "Em uso"
        MAINTENANCE = "maintenance", "Em manutenção"
        RETIRED = "retired", "Baixado"

    code = models.CharField("Patrimônio / etiqueta", max_length=40)
    name = models.CharField("Bem", max_length=180)
    serial_number = models.CharField("Número de série", max_length=100, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True, blank=True, related_name="assets", verbose_name="Categoria")
    location = models.CharField("Localização", max_length=150, blank=True)
    custodian = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="inventory_assets", verbose_name="Responsável")
    acquired_on = models.DateField("Data de aquisição", null=True, blank=True)
    acquisition_value = models.DecimalField("Valor de aquisição (R$)", max_digits=14, decimal_places=2, null=True, blank=True)
    status = models.CharField("Situação", max_length=12, choices=Status.choices, default=Status.AVAILABLE)
    notes = models.TextField("Observações", max_length=3000, blank=True, validators=[MaxLengthValidator(3000)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="inventory_asset_code_unique"),
            models.CheckConstraint(condition=Q(acquisition_value__isnull=True) | Q(acquisition_value__gte=0), name="inventory_asset_value_nonnegative"),
        ]

    def __str__(self):
        return f"{self.code} · {self.name}"

    def clean(self):
        super().clean()
        if self.acquisition_value is not None and self.acquisition_value < 0:
            raise ValidationError({"acquisition_value": "O valor não pode ser negativo."})
        if self.acquired_on and self.acquired_on > timezone.localdate():
            raise ValidationError({"acquired_on": "A aquisição não pode estar no futuro."})
        if self.custodian_id:
            from apps.core.models import Membership
            if not Membership.objects.filter(organization_id=self.organization_id, user_id=self.custodian_id, is_active=True, user__is_active=True).exclude(role="client").exists():
                raise ValidationError({"custodian": "Selecione uma pessoa ativa da equipe interna."})

    def save(self, *args, **kwargs):
        if not getattr(self, "_inventory_transition", False):
            raise ValidationError("Altere o patrimônio pelo serviço que preserva seu histórico.")
        return super().save(*args, **kwargs)


class AssetEvent(ImmutableTenantModel):
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inventory_asset_events")
    reason = models.CharField("Motivo", max_length=500)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
