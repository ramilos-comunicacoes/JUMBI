"""Authorized, idempotent inventory writes. The office lock serializes receipts."""
import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid5

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.billing.services import has_advanced, require_access
from apps.core.models import Membership, Organization
from apps.legal.services import audit
from .models import Asset, AssetEvent, Category, Movement, Product, Purchase, PurchaseItem, StockLot, Supplier


MAX_QUANTITY = Decimal("999999999.999")
MAX_UNIT_COST = Decimal("9999999999.99")
MODELS = (Category, Supplier, Product, StockLot, Movement, Purchase, PurchaseItem, Asset, AssetEvent)


def can_manage_inventory(actor, organization):
    return bool(actor and actor.is_authenticated and actor.is_active and organization and
        Organization.objects.filter(pk=organization.pk, status="active", business_type="office").exists() and
        Membership.objects.filter(user=actor, user__is_active=True, organization=organization, is_active=True, role__in=["owner", "manager"]).exists())


def require_inventory_access(actor, organization):
    if not can_manage_inventory(actor, organization):
        raise PermissionDenied("Somente a direção e a gestão podem acessar inventário e estoque.")
    require_access(organization, advanced=True)


def visible_records(actor, organization, model, *, for_export=False):
    if model not in MODELS:
        raise ValueError("Modelo de inventário não reconhecido.")
    if not can_manage_inventory(actor, organization) or (not for_export and not has_advanced(organization)):
        return model.objects.none()
    return model.objects.filter(organization=organization)


def products_with_stock(actor, organization, *, for_export=False):
    return visible_records(actor, organization, Product, for_export=for_export).select_related("category").annotate(
        stock_total=Coalesce(Sum("lots__quantity"), Value(Decimal("0")), output_field=DecimalField(max_digits=18, decimal_places=3))
    ).order_by("name", "pk")


def stock_summary(actor, organization):
    products = products_with_stock(actor, organization)
    lots = visible_records(actor, organization, StockLot).filter(quantity__gt=0).select_related("product")
    today = timezone.localdate()
    low = products.filter(is_active=True, stock_total__lte=F("minimum_stock"))
    expiring = lots.filter(expires_on__gte=today, expires_on__lte=today + timedelta(days=30))
    expired = lots.filter(expires_on__lt=today)
    assets = visible_records(actor, organization, Asset)
    return {
        "products_count": products.filter(is_active=True).count(),
        "low_stock_count": low.count(), "low_stock": low[:8],
        "expiring_count": expiring.count(), "expiring_lots": expiring[:8],
        "expired_count": expired.count(), "expired_lots": expired[:8],
        "assets_count": assets.exclude(status=Asset.Status.RETIRED).count(),
        "maintenance_count": assets.filter(status=Asset.Status.MAINTENANCE).count(),
        "pending_purchases_count": visible_records(actor, organization, Purchase).filter(status=Purchase.Status.DRAFT).count(),
    }


def _lock_context(actor, organization):
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    require_inventory_access(actor, organization)
    return organization


def _key(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Identificação inválida. Abra uma nova operação.") from None


def _text(value, label, limit, *, required=True):
    value = str(value or "").strip()
    if (required and not value) or len(value) > limit:
        raise ValidationError(f"Informe {label}, com até {limit} caracteres.")
    return value


def _decimal(value, *, places=3, allow_zero=False, maximum=MAX_QUANTITY):
    quantum = Decimal("0.001") if places == 3 else Decimal("0.01")
    if isinstance(value, (float, bool)):
        raise ValidationError("Informe números decimais exatos, sem arredondamento automático.")
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or (result == 0 and not allow_zero) or result > maximum or result != result.quantize(quantum):
            raise InvalidOperation
    except (TypeError, ValueError, InvalidOperation):
        raise ValidationError(f"Informe um valor {'não negativo' if allow_zero else 'positivo'} com até {places} casas decimais.") from None
    return result.quantize(quantum)


def _date(value, label, *, optional=False):
    if optional and value is None:
        return None
    if type(value) is not date:
        raise ValidationError(f"Informe {label} válida.")
    return value


def _fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _transition(instance, **kwargs):
    instance._inventory_transition = True
    try:
        instance.save(**kwargs)
    finally:
        del instance._inventory_transition
    return instance


def _related(model, value, organization, label):
    if not isinstance(value, model) or not value.pk:
        raise ValidationError(f"Selecione {label} deste escritório.")
    obj = model.objects.filter(pk=value.pk, organization=organization).first()
    if obj is None:
        raise ValidationError(f"Selecione {label} deste escritório.")
    return obj


def _asset_snapshot(asset):
    fields = ["code", "name", "serial_number", "category_id", "location", "custodian_id", "acquired_on", "acquisition_value", "status", "notes"]
    return {key: str(value) if isinstance(value := getattr(asset, key), (Decimal, date)) else value for key in fields}


@transaction.atomic
def save_record(*, instance, actor, reason="Cadastro atualizado."):
    if type(instance) not in (Category, Supplier, Product, Asset):
        raise ValidationError("Use a operação específica deste registro.")
    organization = _lock_context(actor, instance.organization)
    previous = None
    if instance.pk:
        previous = type(instance).objects.select_for_update().filter(pk=instance.pk, organization=organization).first()
        if previous is None:
            raise ValidationError("O registro não pertence a este escritório.")
    reason = _text(reason, "o motivo", 500)
    if isinstance(instance, Asset):
        if instance.acquisition_value is not None:
            instance.acquisition_value = _decimal(instance.acquisition_value, places=2, allow_zero=True, maximum=Decimal("999999999999.99"))
        before = _asset_snapshot(previous) if previous else {}
        _transition(instance)
        after = _asset_snapshot(instance)
        if before != after:
            AssetEvent.objects.create(organization=organization, asset=instance, actor=actor, reason=reason, before=before, after=after)
    else:
        instance.save()
    audit(organization=organization, actor=actor, action="inventory.updated" if previous else "inventory.created", obj=instance, description=reason)
    return instance


def _existing_operation(organization, operation_key, request_hash):
    existing = Movement.objects.filter(organization=organization, operation_key=operation_key).first()
    if existing and existing.request_hash != request_hash:
        raise ValidationError("Esta solicitação já foi usada com outros dados. Abra uma nova operação.")
    return existing


def _post_movement(*, organization, actor, product, lot, kind, delta, reason, operation_key, request_hash, reversal_of=None, purchase_item=None):
    balance = lot.quantity + delta
    if balance < 0:
        raise ValidationError(f"Saldo insuficiente no lote {lot.code}. Disponível: {lot.quantity} {product.unit}.")
    if balance > MAX_QUANTITY:
        raise ValidationError("O saldo deste lote excede o limite permitido.")
    lot.quantity = balance
    _transition(lot, update_fields=["quantity"])
    movement = Movement(organization=organization, actor=actor, product=product, lot=lot, kind=kind, quantity=delta,
        balance_after=balance, reason=reason, operation_key=operation_key, request_hash=request_hash, reversal_of=reversal_of, purchase_item=purchase_item)
    _transition(movement)
    audit(organization=organization, actor=actor, action="inventory.movement", obj=movement,
        description=f"{movement.get_kind_display()}: {delta} {product.unit}; lote {lot.code}; saldo {balance}. {reason}")
    return movement


@transaction.atomic
def record_movement(*, organization, actor, product, kind, quantity, reason, operation_key, lot=None, lot_code="", expires_on=None):
    organization = _lock_context(actor, organization)
    product = _related(Product, product, organization, "um material")
    if kind not in {Movement.Kind.ENTRY, Movement.Kind.CONSUMPTION, Movement.Kind.LOSS, Movement.Kind.COUNT}:
        raise ValidationError("Escolha entrada, consumo, perda ou contagem física.")
    quantity = _decimal(quantity, allow_zero=kind == Movement.Kind.COUNT)
    reason = _text(reason, "o motivo", 500)
    operation_key = _key(operation_key)
    expires_on = _date(expires_on, "uma validade", optional=True)
    original_lot_id = getattr(lot, "pk", None)
    lot_code = _text(lot_code, "o lote", 80, required=lot is None and kind == Movement.Kind.ENTRY)
    request_hash = _fingerprint(dict(actor=actor.pk, product=product.pk, kind=kind, quantity=quantity, reason=reason,
        lot=original_lot_id, lot_code=lot_code, expires_on=expires_on))
    existing = _existing_operation(organization, operation_key, request_hash)
    if existing:
        return existing
    if not product.is_active:
        raise ValidationError("Reative o material antes de movimentar seu estoque.")
    if lot is not None:
        lot = _related(StockLot, lot, organization, "um lote")
        if lot.product_id != product.pk:
            raise ValidationError("Selecione um lote deste material.")
        if expires_on is not None and lot.expires_on != expires_on:
            raise ValidationError("A validade do lote já está registrada e deve ser preservada.")
        lot = StockLot.objects.select_for_update().get(pk=lot.pk)
    elif kind == Movement.Kind.ENTRY:
        lot = StockLot.objects.select_for_update().filter(organization=organization, product=product, code=lot_code).first()
        if lot and lot.expires_on != expires_on:
            raise ValidationError("Este lote possui outra validade. Confira a entrada ou escolha outro código.")
        if not lot:
            lot = _transition(StockLot(organization=organization, product=product, code=lot_code, expires_on=expires_on))
    else:
        raise ValidationError("Selecione o lote que será consumido, baixado ou contado.")
    if kind == Movement.Kind.CONSUMPTION and lot.expires_on and lot.expires_on < timezone.localdate():
        raise ValidationError("O lote está vencido. Registre a perda ou confira a contagem; não registre consumo.")
    delta = quantity if kind == Movement.Kind.ENTRY else (quantity - lot.quantity if kind == Movement.Kind.COUNT else -quantity)
    return _post_movement(organization=organization, actor=actor, product=product, lot=lot, kind=kind, delta=delta,
        reason=reason, operation_key=operation_key, request_hash=request_hash)


@transaction.atomic
def reverse_movement(*, movement, actor, reason, operation_key):
    organization = _lock_context(actor, movement.organization)
    movement = _related(Movement, movement, organization, "uma movimentação")
    reason = _text(reason, "o motivo do estorno", 500)
    operation_key = _key(operation_key)
    fingerprint = _fingerprint(dict(actor=actor.pk, reversal_of=movement.pk, reason=reason))
    existing = _existing_operation(organization, operation_key, fingerprint)
    if existing:
        return existing
    if movement.kind == Movement.Kind.REVERSAL or Movement.objects.filter(reversal_of=movement).exists():
        raise ValidationError("A movimentação já foi estornada ou é um estorno.")
    lot = StockLot.objects.select_for_update().get(pk=movement.lot_id, organization=organization)
    return _post_movement(organization=organization, actor=actor, product=movement.product, lot=lot,
        kind=Movement.Kind.REVERSAL, delta=-movement.quantity, reason=reason, operation_key=operation_key,
        request_hash=fingerprint, reversal_of=movement)


@transaction.atomic
def create_purchase(*, organization, actor, items, operation_key, supplier=None, reference="", notes="", purchased_on=None):
    organization = _lock_context(actor, organization)
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= 30:
        raise ValidationError("Cadastre entre 1 e 30 itens por compra.")
    operation_key = _key(operation_key)
    purchased_on = _date(timezone.localdate() if purchased_on is None else purchased_on, "uma data de compra")
    if purchased_on > timezone.localdate():
        raise ValidationError("A data da compra não pode estar no futuro.")
    reference = _text(reference, "a referência", 100, required=False)
    notes = _text(notes, "as observações", 3000, required=False)
    supplier = _related(Supplier, supplier, organization, "um fornecedor") if supplier else None
    rows = []
    fingerprints = []
    seen = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ValidationError("Informe os dados de cada item da compra.")
        product = _related(Product, raw.get("product"), organization, "um material")
        quantity = _decimal(raw.get("quantity"))
        unit_cost = _decimal(raw.get("unit_cost"), places=2, allow_zero=True, maximum=MAX_UNIT_COST)
        lot_code = _text(raw.get("lot_code"), "o lote", 80)
        expires_on = _date(raw.get("expires_on"), "uma validade", optional=True)
        identity = (product.pk, lot_code)
        if identity in seen:
            raise ValidationError("Agrupe o mesmo material e lote em uma única linha da compra.")
        seen.add(identity)
        rows.append(dict(product=product, quantity=quantity, unit_cost=unit_cost, lot_code=lot_code, expires_on=expires_on))
        fingerprints.append(dict(product=product.pk, quantity=quantity, unit_cost=unit_cost, lot_code=lot_code, expires_on=expires_on))
    fingerprint = _fingerprint(dict(actor=actor.pk, supplier=getattr(supplier, "pk", None), reference=reference, notes=notes, purchased_on=purchased_on, items=fingerprints))
    existing = Purchase.objects.filter(organization=organization, operation_key=operation_key).first()
    if existing:
        if existing.request_hash != fingerprint:
            raise ValidationError("Esta solicitação já foi usada com outra compra. Abra um novo cadastro.")
        return existing
    if supplier and not supplier.is_active:
        raise ValidationError("Selecione um fornecedor ativo.")
    if any(not row["product"].is_active for row in rows):
        raise ValidationError("Selecione somente materiais ativos.")
    purchase = _transition(Purchase(organization=organization, created_by=actor, supplier=supplier, reference=reference,
        notes=notes, purchased_on=purchased_on, operation_key=operation_key, request_hash=fingerprint))
    for row in rows:
        PurchaseItem.objects.create(organization=organization, purchase=purchase, **row)
    audit(organization=organization, actor=actor, action="inventory.purchase_created", obj=purchase,
        description=f"{len(rows)} itens. Estoque aguardando recebimento. Nenhum pagamento foi registrado.")
    return purchase


@transaction.atomic
def receive_purchase(*, purchase, actor):
    organization = _lock_context(actor, purchase.organization)
    purchase = Purchase.objects.select_for_update().get(pk=purchase.pk, organization=organization)
    if purchase.status == Purchase.Status.RECEIVED:
        return purchase
    if purchase.status != Purchase.Status.DRAFT:
        raise ValidationError("A compra cancelada não pode ser recebida.")
    items = list(purchase.items.select_related("product"))
    if not items:
        raise ValidationError("A compra precisa ter itens antes do recebimento.")
    for item in items:
        if not item.product.is_active:
            raise ValidationError("Reative todos os materiais da compra antes de recebê-la.")
        lot = StockLot.objects.select_for_update().filter(organization=organization, product=item.product, code=item.lot_code).first()
        if lot and lot.expires_on != item.expires_on:
            raise ValidationError(f"Confira a validade do lote {item.lot_code}; ela difere do cadastro existente.")
        if not lot:
            lot = _transition(StockLot(organization=organization, product=item.product, code=item.lot_code, expires_on=item.expires_on))
        operation_key = uuid5(purchase.operation_key, f"receipt:{item.pk}")
        _post_movement(organization=organization, actor=actor, product=item.product, lot=lot, kind=Movement.Kind.ENTRY,
            delta=item.quantity, reason=f"Recebimento da compra #{purchase.pk}.", operation_key=operation_key,
            request_hash=_fingerprint(dict(purchase=purchase.pk, item=item.pk)), purchase_item=item)
    purchase.status = Purchase.Status.RECEIVED
    purchase.received_at = timezone.now()
    purchase.received_by = actor
    _transition(purchase, update_fields=["status", "received_at", "received_by"])
    audit(organization=organization, actor=actor, action="inventory.purchase_received", obj=purchase,
        description=f"{len(items)} entradas registradas no estoque. Nenhum lançamento financeiro ou pagamento foi criado.")
    return purchase


@transaction.atomic
def cancel_purchase(*, purchase, actor, reason):
    organization = _lock_context(actor, purchase.organization)
    purchase = Purchase.objects.select_for_update().get(pk=purchase.pk, organization=organization)
    reason = _text(reason, "o motivo do cancelamento", 500)
    if purchase.status == Purchase.Status.CANCELLED:
        if purchase.cancellation_reason != reason:
            raise ValidationError("A compra já foi cancelada com outro motivo.")
        return purchase
    if purchase.status != Purchase.Status.DRAFT:
        raise ValidationError("Uma compra recebida deve manter o histórico. Corrija entradas pelos estornos de movimentação.")
    purchase.status = Purchase.Status.CANCELLED
    purchase.cancellation_reason = reason
    _transition(purchase, update_fields=["status", "cancellation_reason"])
    audit(organization=organization, actor=actor, action="inventory.purchase_cancelled", obj=purchase, description=reason)
    return purchase
