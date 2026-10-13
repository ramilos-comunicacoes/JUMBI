from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.models import AuditEvent, FinanceEntry, Payment
from .forms import AssetForm, MovementForm, ProductForm, PurchaseItemFormSet
from .models import Asset, AssetEvent, Category, Movement, Product, Purchase, PurchaseItem, StockLot, Supplier
from .services import cancel_purchase, create_purchase, products_with_stock, receive_purchase, record_movement, reverse_movement, save_record, stock_summary, visible_records


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class InventoryDomainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Estoque Aurora", slug="inventory-aurora", business_type="office")
        cls.other = Organization.objects.create(name="Outro escritório", slug="inventory-other", business_type="office")
        cls.users = {}
        for role in ("owner", "manager", "operator", "viewer", "client"):
            user = get_user_model().objects.create_user(email=f"inventory-{role}@example.test")
            Membership.objects.create(organization=cls.org, user=user, role=role)
            cls.users[role] = user
        cls.owner = cls.users["owner"]
        cls.outsider = get_user_model().objects.create_user(email="inventory-other@example.test")
        Membership.objects.create(organization=cls.other, user=cls.outsider, role="owner")
        cls.category = Category.objects.create(organization=cls.org, name="Materiais administrativos")
        cls.foreign_category = Category.objects.create(organization=cls.other, name="Categoria externa")
        cls.product = Product.objects.create(organization=cls.org, code="PAP-1", name="Papel A4", unit="pct", category=cls.category, minimum_stock="3")
        cls.other_product = Product.objects.create(organization=cls.other, code="EXT-1", name="Material externo")
        cls.supplier = Supplier.objects.create(organization=cls.org, name="Papelaria exemplo")

    def entry(self, **kwargs):
        data = dict(organization=self.org, actor=self.owner, product=self.product, kind="entry", quantity="10.000", lot_code="LOTE-1", reason="Saldo de abertura conferido", operation_key=uuid4())
        data.update(kwargs)
        return record_movement(**data)

    def move(self, lot, **kwargs):
        data = dict(organization=self.org, actor=self.owner, product=self.product, lot=lot, kind="consumption", quantity="2.000", reason="Uso administrativo", operation_key=uuid4())
        data.update(kwargs)
        return record_movement(**data)

    def purchase(self, **kwargs):
        data = dict(organization=self.org, actor=self.owner, supplier=self.supplier, operation_key=uuid4(), reference="NF-001", purchased_on=timezone.localdate(), items=[dict(product=self.product, quantity="2.500", unit_cost="10.00", lot_code="COMPRA-1", expires_on=None)])
        data.update(kwargs)
        return create_purchase(**data)

    def test_stock_entries_decimal_consumption_and_loss_keep_signed_ledger(self):
        first = self.entry(quantity="10.750")
        second = self.move(first.lot, quantity="2.500")
        third = self.move(first.lot, quantity="1.125", kind="loss", reason="Embalagem danificada")
        self.assertEqual([m.quantity for m in (first, second, third)], [Decimal("10.750"), Decimal("-2.500"), Decimal("-1.125")])
        first.lot.refresh_from_db()
        self.assertEqual(first.lot.quantity, Decimal("7.125"))
        self.assertEqual(self.product.current_stock, Decimal("7.125"))
        self.assertEqual(Movement.objects.count(), 3)
        self.assertEqual(AuditEvent.objects.filter(action="inventory.movement").count(), 3)

    def test_physical_count_is_absolute_including_zero_and_unchanged_count(self):
        lot = self.entry().lot
        result = self.move(lot, kind="count", quantity="4", reason="Contagem física por conferente")
        self.assertEqual(result.quantity, Decimal("-6"))
        unchanged = self.move(lot, kind="count", quantity="4")
        self.assertEqual(unchanged.quantity, 0)
        zero = self.move(lot, kind="count", quantity="0")
        self.assertEqual(zero.quantity, Decimal("-4"))
        self.assertEqual(self.product.current_stock, 0)

    def test_insufficient_stock_rolls_back_and_lots_do_not_borrow_each_others_balance(self):
        first = self.entry(quantity="1").lot
        self.entry(quantity="100", lot_code="OTHER-LOT")
        with self.assertRaises(ValidationError):
            self.move(first, quantity="2")
        self.assertEqual(self.product.current_stock, 101)
        self.assertEqual(Movement.objects.count(), 2)

    def test_duplicate_entry_and_count_are_idempotent_and_payload_changes_are_rejected(self):
        key = uuid4()
        first = self.entry(operation_key=key)
        self.assertEqual(self.entry(operation_key=key).pk, first.pk)
        self.assertEqual(self.product.current_stock, 10)
        with self.assertRaises(ValidationError):
            self.entry(operation_key=key, quantity="11")
        count_key = uuid4()
        first_count = self.move(first.lot, operation_key=count_key, kind="count", quantity="6")
        self.move(first.lot, quantity="1")
        retry = self.move(first.lot, operation_key=count_key, kind="count", quantity="6")
        self.assertEqual(first_count.pk, retry.pk)
        self.assertEqual(self.product.current_stock, 5)

    def test_invalid_quantities_and_empty_reasons_never_write(self):
        for quantity in [True, 1.5, "NaN", "Infinity", "0", "-1", "0.0001", "1000000000"]:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                self.entry(quantity=quantity)
        for extra in [{"reason": "   "}, {"operation_key": "bad"}, {"lot_code": ""}, {"kind": "reversal"}, {"expires_on": "2026-12-01"}]:
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                self.entry(**extra)
        self.assertFalse(StockLot.objects.exists())
        self.assertFalse(Movement.objects.exists())

    def test_stock_overflow_rolls_back_balance_and_ledger(self):
        first = self.entry(quantity="999999999.999")
        with self.assertRaises(ValidationError):
            self.entry(quantity="0.001")
        self.assertEqual(self.product.current_stock, Decimal("999999999.999"))
        self.assertEqual(Movement.objects.count(), 1)

    def test_foreign_product_lot_and_category_are_rejected(self):
        other_lot = self.entry(organization=self.other, actor=self.outsider, product=self.other_product).lot
        for change in [{"product": self.other_product}, {"lot": other_lot}, {"organization": self.other}]:
            with self.subTest(change=change), self.assertRaises((ValidationError, PermissionDenied)):
                self.entry(**change)
        self.product.category = self.foreign_category
        with self.assertRaises(ValidationError):
            save_record(instance=self.product, actor=self.owner)
        self.assertFalse(Movement.objects.filter(organization=self.org).exists())

    def test_same_office_different_product_lot_is_rejected(self):
        second = Product.objects.create(organization=self.org, code="PAP-2", name="Envelope")
        lot = self.entry(product=second).lot
        with self.assertRaises(ValidationError):
            self.move(lot)
        self.assertEqual(second.current_stock, 10)

    def test_membership_roles_revocation_and_stale_user_are_rechecked(self):
        self.entry(actor=self.users["manager"])
        for role in ("operator", "viewer", "client"):
            with self.subTest(role=role), self.assertRaises(PermissionDenied):
                self.entry(actor=self.users[role])
            self.assertFalse(visible_records(self.users[role], self.org, Product).exists())
        self.assertFalse(visible_records(self.outsider, self.org, Product, for_export=True).exists())
        Membership.objects.filter(organization=self.org, user=self.owner).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.entry()
        Membership.objects.filter(organization=self.org, user=self.owner).update(is_active=True)
        get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.entry()

    def test_suspended_organization_is_rechecked_from_database(self):
        Organization.objects.filter(pk=self.org.pk).update(status="suspended")
        with self.assertRaises(PermissionDenied):
            self.entry()
        self.assertFalse(visible_records(self.owner, self.org, Product, for_export=True).exists())

    @override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
    def test_max_plan_and_expiry_gate_writes_but_allow_historical_manager_export(self):
        subscription = OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
        with self.assertRaises(PermissionDenied):
            self.entry()
        self.assertFalse(visible_records(self.owner, self.org, Product).exists())
        subscription.plan = "max"
        subscription.save()
        self.entry()
        subscription.expires_at = timezone.now() - timedelta(seconds=1)
        subscription.save()
        with self.assertRaises(PermissionDenied):
            self.entry()
        self.assertFalse(visible_records(self.owner, self.org, Movement).exists())
        self.assertEqual(visible_records(self.owner, self.org, Movement, for_export=True).count(), 1)

    def test_reversal_is_exact_idempotent_and_preserves_origin(self):
        entry = self.entry()
        used = self.move(entry.lot, quantity="3")
        key = uuid4()
        reversal = reverse_movement(movement=used, actor=self.owner, reason="Saída em duplicidade", operation_key=key)
        self.assertEqual(reversal.quantity, 3)
        self.assertEqual(reversal.reversal_of_id, used.pk)
        self.assertEqual(self.product.current_stock, 10)
        self.assertEqual(reverse_movement(movement=used, actor=self.owner, reason="Saída em duplicidade", operation_key=key).pk, reversal.pk)
        for target in [used, reversal]:
            with self.assertRaises(ValidationError):
                reverse_movement(movement=target, actor=self.owner, reason="Outro estorno", operation_key=uuid4())
        used.refresh_from_db()
        self.assertEqual(used.quantity, -3)

    def test_entry_reversal_cannot_make_consumed_lot_negative(self):
        entry = self.entry()
        self.move(entry.lot)
        with self.assertRaises(ValidationError):
            reverse_movement(movement=entry, actor=self.owner, reason="Entrada indevida", operation_key=uuid4())
        self.assertEqual(self.product.current_stock, 8)

    def test_stock_lot_identification_and_unit_are_preserved(self):
        entry = self.entry(expires_on=timezone.localdate() + timedelta(days=10))
        with self.assertRaises(ValidationError):
            self.entry(expires_on=None)
        self.product.unit = "kg"
        with self.assertRaises(ValidationError):
            save_record(instance=self.product, actor=self.owner)
        entry.lot.quantity = 999
        with self.assertRaises(ValidationError):
            entry.lot.save()
        with self.assertRaises(ValidationError):
            StockLot.objects.filter(pk=entry.lot_id).update(quantity=999)

    def test_movements_and_history_cannot_be_updated_or_deleted(self):
        movement = self.entry()
        for mutate in [lambda: movement.delete(), lambda: Movement.objects.filter(pk=movement.pk).delete(), lambda: Movement.objects.filter(pk=movement.pk).update(reason="Oculto"), lambda: movement.save(), lambda: movement.lot.delete()]:
            with self.subTest(mutate=mutate), self.assertRaises(ValidationError):
                mutate()
        self.assertEqual(self.product.current_stock, 10)

    def test_expiry_alerts_only_include_remaining_stock_and_consumption_blocks_expired_lots(self):
        today = timezone.localdate()
        expired = self.entry(lot_code="EXP", expires_on=today - timedelta(days=1)).lot
        soon = self.entry(lot_code="SOON", expires_on=today + timedelta(days=10)).lot
        consumed = self.entry(lot_code="USED", expires_on=today + timedelta(days=5)).lot
        self.move(consumed, quantity="10")
        with self.assertRaises(ValidationError):
            self.move(expired, quantity="1")
        self.move(expired, quantity="2", kind="loss", reason="Descarte por validade")
        summary = stock_summary(self.owner, self.org)
        self.assertEqual(summary["expired_count"], 1)
        self.assertEqual(summary["expiring_count"], 1)
        self.assertEqual(list(summary["expiring_lots"])[0].pk, soon.pk)
        self.move(expired, quantity="8", kind="loss")
        self.assertEqual(stock_summary(self.owner, self.org)["expired_count"], 0)

    def test_low_stock_counts_total_across_lots_and_excludes_inactive_materials(self):
        self.assertEqual(stock_summary(self.owner, self.org)["low_stock_count"], 1)
        self.entry(quantity="2", lot_code="A")
        self.entry(quantity="2", lot_code="B")
        self.assertEqual(stock_summary(self.owner, self.org)["low_stock_count"], 0)
        product = products_with_stock(self.owner, self.org).get(pk=self.product.pk)
        self.assertTrue(products_with_stock(self.owner, self.org).ordered)
        self.assertEqual(product.current_stock, 4)
        self.product.is_active = False
        save_record(instance=self.product, actor=self.owner)
        with self.assertRaises(ValidationError):
            self.entry()
        self.assertEqual(stock_summary(self.owner, self.org)["products_count"], 0)

    def test_atomic_failure_never_changes_lot_or_audit(self):
        first = self.entry()
        with patch("apps.inventory.services.audit", side_effect=ValidationError("Falha no registro")):
            with self.assertRaises(ValidationError):
                self.move(first.lot)
        self.assertEqual(self.product.current_stock, 10)
        self.assertEqual(Movement.objects.count(), 1)

    def test_purchase_draft_receipt_and_retries_do_not_record_finance(self):
        key = uuid4()
        purchase = self.purchase(operation_key=key)
        self.supplier.is_active = False
        self.supplier.save()
        self.assertEqual(self.purchase(operation_key=key).pk, purchase.pk)
        self.assertEqual(purchase.total, Decimal("25.00"))
        self.assertFalse(StockLot.objects.exists())
        receipt = receive_purchase(purchase=purchase, actor=self.owner)
        self.assertEqual(receipt.status, "received")
        self.assertEqual(receive_purchase(purchase=purchase, actor=self.users["manager"]).pk, receipt.pk)
        self.assertEqual(self.product.current_stock, Decimal("2.5"))
        self.assertEqual(Movement.objects.count(), 1)
        self.assertEqual(Movement.objects.get().purchase_item_id, purchase.items.get().pk)
        self.assertFalse(FinanceEntry.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_purchase_cancellation_has_no_stock_effect_and_cannot_receive_afterwards(self):
        purchase = self.purchase()
        cancelled = cancel_purchase(purchase=purchase, actor=self.owner, reason="Pedido cancelado")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(cancel_purchase(purchase=purchase, actor=self.owner, reason="Pedido cancelado").pk, purchase.pk)
        with self.assertRaises(ValidationError):
            receive_purchase(purchase=purchase, actor=self.owner)
        with self.assertRaises(ValidationError):
            cancel_purchase(purchase=purchase, actor=self.owner, reason="Outro motivo")
        self.assertFalse(Movement.objects.exists())

    def test_received_purchase_cannot_cancel_but_corrective_reversal_preserves_receipt(self):
        purchase = receive_purchase(purchase=self.purchase(), actor=self.owner)
        with self.assertRaises(ValidationError):
            cancel_purchase(purchase=purchase, actor=self.owner, reason="Cancelamento tardio")
        reverse_movement(movement=Movement.objects.get(), actor=self.owner, reason="Devolução integral", operation_key=uuid4())
        self.assertEqual(self.product.current_stock, 0)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, "received")
        self.assertEqual(purchase.items.count(), 1)

    def test_receipt_rolls_back_all_items_on_last_lot_conflict(self):
        second = Product.objects.create(organization=self.org, code="P2", name="Outro material")
        self.entry(product=second, lot_code="CONFLICT", expires_on=date(2030, 1, 1))
        purchase = self.purchase(items=[dict(product=self.product, quantity="2", unit_cost="1", lot_code="GOOD"), dict(product=second, quantity="2", unit_cost="1", lot_code="CONFLICT", expires_on=date(2030, 1, 2))])
        with self.assertRaises(ValidationError):
            receive_purchase(purchase=purchase, actor=self.owner)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, "draft")
        self.assertFalse(StockLot.objects.filter(code="GOOD").exists())
        self.assertEqual(Movement.objects.count(), 1)
        self.assertEqual(self.product.current_stock, 0)

    def test_purchase_invalid_foreign_duplicate_items_and_key_reuse_rejected(self):
        for rows in [[], [dict(product=self.other_product, quantity="1", unit_cost="1", lot_code="X")], [dict(product=self.product, quantity="-1", unit_cost="1", lot_code="X")], [dict(product=self.product, quantity="1", unit_cost="-1", lot_code="X")], [dict(product=self.product, quantity="1", unit_cost="1", lot_code="X")] * 2]:
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                self.purchase(items=rows)
        key = uuid4()
        self.purchase(operation_key=key)
        with self.assertRaises(ValidationError):
            self.purchase(operation_key=key, reference="CHANGED")
        self.assertEqual(Purchase.objects.count(), 1)

    def test_purchase_inactive_material_and_foreign_supplier_rejected(self):
        foreign_supplier = Supplier.objects.create(organization=self.other, name="Fornecedor externo")
        with self.assertRaises(ValidationError):
            self.purchase(supplier=foreign_supplier)
        purchase = self.purchase()
        self.product.is_active = False
        save_record(instance=self.product, actor=self.owner)
        with self.assertRaises(ValidationError):
            receive_purchase(purchase=purchase, actor=self.owner)
        with self.assertRaises(ValidationError):
            self.purchase()
        self.assertFalse(Movement.objects.exists())

    def test_purchase_items_and_transition_are_not_editable_through_model(self):
        purchase = self.purchase()
        item = purchase.items.get()
        item.quantity = 50
        with self.assertRaises(ValidationError):
            item.save()
        purchase.status = "received"
        with self.assertRaises(ValidationError):
            purchase.save()

    def test_assets_track_custody_location_and_retirement_as_history(self):
        asset = Asset(organization=self.org, code="PAT-1", name="Notebook", acquisition_value="1500.00")
        save_record(instance=asset, actor=self.owner, reason="Aquisição conferida")
        asset.custodian = self.users["operator"]
        asset.location = "Sala 2"
        asset.status = "in_use"
        save_record(instance=asset, actor=self.owner, reason="Entrega ao responsável")
        asset.status = "retired"
        save_record(instance=asset, actor=self.owner, reason="Baixa por dano permanente")
        self.assertEqual(asset.events.count(), 3)
        event = asset.events.first()
        self.assertEqual(event.before["status"], "in_use")
        self.assertEqual(event.after["status"], "retired")
        self.assertEqual(stock_summary(self.owner, self.org)["assets_count"], 0)
        self.assertFalse(FinanceEntry.objects.exists())
        with self.assertRaises(ValidationError):
            event.delete()
        with self.assertRaises(ValidationError):
            asset.delete()

    def test_assets_refuse_client_foreign_or_revoked_custodians_and_invalid_values(self):
        for user in [self.users["client"], self.outsider]:
            with self.subTest(user=user.pk), self.assertRaises(ValidationError):
                save_record(instance=Asset(organization=self.org, code=f"A-{user.pk}", name="Computador", custodian=user), actor=self.owner)
        Membership.objects.filter(organization=self.org, user=self.users["operator"]).update(is_active=False)
        with self.assertRaises(ValidationError):
            save_record(instance=Asset(organization=self.org, code="A-INACTIVE", name="Computador", custodian=self.users["operator"]), actor=self.owner)
        for extra in [{"acquisition_value": -1}, {"acquired_on": timezone.localdate() + timedelta(days=1)}]:
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                save_record(instance=Asset(organization=self.org, code="BAD", name="Computador", **extra), actor=self.owner)
        self.assertFalse(Asset.objects.exists())

    def test_asset_event_failure_rolls_back_asset_update(self):
        asset = save_record(instance=Asset(organization=self.org, code="A", name="Notebook"), actor=self.owner)
        asset.status = "maintenance"
        with patch("apps.inventory.services.AssetEvent.objects.create", side_effect=ValidationError("Falha no histórico")):
            with self.assertRaises(ValidationError):
                save_record(instance=asset, actor=self.owner)
        asset.refresh_from_db()
        self.assertEqual(asset.status, "available")
        self.assertEqual(asset.events.count(), 1)

    def test_long_text_and_inexact_asset_values_rejected_at_domain_boundary(self):
        for value in [12.5, True, "NaN", "Infinity", "1.001"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                save_record(instance=Asset(organization=self.org, code="EXACT", name="Bem", acquisition_value=value), actor=self.owner)
        with self.assertRaises(ValidationError):
            save_record(instance=Asset(organization=self.org, code="LONG", name="Bem", notes="x" * 3001), actor=self.owner)
        with self.assertRaises(ValidationError):
            self.purchase(notes="x" * 3001)
        with self.assertRaises(ValidationError):
            self.purchase(purchased_on="")
        self.assertFalse(Asset.objects.exists())
        self.assertFalse(Purchase.objects.exists())
        self.assertFalse(AssetEvent.objects.exists())

    def test_catalog_forms_scope_foreign_keys_and_asset_custodians(self):
        form = ProductForm(dict(code="FORM-1", name="Material", category=self.foreign_category.pk, unit="un", minimum_stock="0", is_active="on"), organization=self.org, actor=self.owner)
        self.assertFalse(form.is_valid())
        self.assertIn("category", form.errors)
        asset = AssetForm(organization=self.org, actor=self.owner)
        ids = set(asset.fields["custodian"].queryset.values_list("pk", flat=True))
        self.assertNotIn(self.users["client"].pk, ids)
        self.assertNotIn(self.outsider.pk, ids)
        self.assertIn(self.users["operator"].pk, ids)

    def test_movement_form_requires_selected_lot_and_valid_operation(self):
        data = dict(operation_key=str(uuid4()), product=self.product.pk, kind="consumption", quantity="0", reason="Conferido")
        form = MovementForm(data, organization=self.org, actor=self.owner)
        self.assertFalse(form.is_valid())
        self.assertIn("lot", form.errors)
        self.assertIn("quantity", form.errors)
        data.update(kind="entry", quantity="1", lot_code="NEW")
        self.assertTrue(MovementForm(data, organization=self.org, actor=self.owner).is_valid())

    def test_purchase_formset_rejects_duplicate_rows_and_excessive_form_count(self):
        data = {"form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "0", "form-MIN_NUM_FORMS": "1", "form-MAX_NUM_FORMS": "30"}
        for i in range(2):
            data.update({f"form-{i}-product": str(self.product.pk), f"form-{i}-quantity": "1", f"form-{i}-unit_cost": "1", f"form-{i}-lot_code": "X"})
        formset = PurchaseItemFormSet(data, form_kwargs={"organization": self.org, "actor": self.owner})
        self.assertFalse(formset.is_valid())
        self.assertIn("Agrupe", str(formset.non_form_errors()))
        data["form-TOTAL_FORMS"] = "2000"
        oversized = PurchaseItemFormSet(data, form_kwargs={"organization": self.org, "actor": self.owner})
        self.assertEqual(len(oversized.forms), 30)
        self.assertFalse(oversized.is_valid())


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class InventoryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Concorrência estoque", slug="inventory-concurrent", business_type="office")
        self.owner = get_user_model().objects.create_user(email="inventory-concurrent@example.test")
        Membership.objects.create(organization=self.org, user=self.owner, role="owner")
        self.product = Product.objects.create(organization=self.org, code="P1", name="Papel")

    def workers(self, callback):
        barrier = Barrier(2)
        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return callback()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return [future.result(timeout=25) for future in [pool.submit(worker), pool.submit(worker)]]

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_identical_entry_adds_stock_once(self):
        key = uuid4()
        def entry():
            return record_movement(organization=self.org, actor=self.owner, product=self.product, kind="entry", quantity="5", lot_code="A", reason="Abertura", operation_key=key).pk
        results = self.workers(entry)
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.product.current_stock, 5)
        self.assertEqual(Movement.objects.count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_withdrawals_never_make_stock_negative(self):
        lot = record_movement(organization=self.org, actor=self.owner, product=self.product, kind="entry", quantity="5", lot_code="A", reason="Abertura", operation_key=uuid4()).lot
        def consume():
            try:
                record_movement(organization=self.org, actor=self.owner, product=self.product, lot=lot, kind="consumption", quantity="4", reason="Consumo", operation_key=uuid4())
                return "ok"
            except ValidationError:
                return "insufficient"
        self.assertCountEqual(self.workers(consume), ["ok", "insufficient"])
        self.assertEqual(self.product.current_stock, 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_receipt_does_not_duplicate_any_purchase_item(self):
        purchase = create_purchase(organization=self.org, actor=self.owner, operation_key=uuid4(), items=[dict(product=self.product, quantity="3", unit_cost="2", lot_code="A"), dict(product=self.product, quantity="7", unit_cost="1", lot_code="B")])
        results = self.workers(lambda: receive_purchase(purchase=purchase, actor=self.owner).pk)
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.product.current_stock, 10)
        self.assertEqual(Movement.objects.count(), 2)
