from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization, User
from apps.core.test_platform import TEST_SETTINGS
from .models import Asset, AssetEvent, Category, Movement, Product, Purchase, StockLot, Supplier
from .services import create_purchase, record_movement, save_record


@override_settings(**{**TEST_SETTINGS, "JUMBI_ENFORCE_SUBSCRIPTIONS": True})
class InventoryViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Escritório do estoque", slug="inventory-http", business_type="office")
        cls.foreign = Organization.objects.create(name="Outro escritório", slug="inventory-http-other", business_type="office")
        cls.subscription = OrganizationSubscription.objects.create(organization=cls.org, plan="max", status="active")
        OrganizationSubscription.objects.create(organization=cls.foreign, plan="max", status="active")
        cls.users = {}
        for role in ["owner", "manager", "operator", "viewer", "client"]:
            user = User.objects.create_user(f"inventory-http-{role}@example.test", "InventoryTests!234567")
            Membership.objects.create(user=user, organization=cls.org, role=role)
            cls.users[role] = user
        cls.owner = cls.users["owner"]
        cls.outsider = User.objects.create_user("inventory-http-other@example.test", "InventoryTests!234568")
        Membership.objects.create(user=cls.outsider, organization=cls.foreign, role="owner")
        cls.category = Category.objects.create(organization=cls.org, name="Expediente")
        cls.foreign_category = Category.objects.create(organization=cls.foreign, name="Categoria de outro escritório")
        cls.product = Product.objects.create(organization=cls.org, code="PAP-HTTP", name="Papel de teste", unit="pct", category=cls.category, minimum_stock="5")
        cls.second_product = Product.objects.create(organization=cls.org, code="TON-HTTP", name="Toner de teste")
        cls.foreign_product = Product.objects.create(organization=cls.foreign, code="FOREIGN", name="Material confidencial estrangeiro")
        cls.supplier = Supplier.objects.create(organization=cls.org, name="Papelaria do teste", email="vendas@example.test")

    def setUp(self):
        self.client.force_login(self.owner)

    def url(self, name, *args):
        return reverse("inventory:" + name, args=args)

    def entry(self, product=None, actor=None, organization=None, **kwargs):
        return record_movement(organization=organization or self.org, actor=actor or self.owner,
            product=product or self.product, kind="entry", quantity="12", reason="Abertura conferida",
            lot_code="LOTE-HTTP", operation_key=uuid4(), **kwargs)

    def purchase(self):
        return create_purchase(organization=self.org, actor=self.owner, supplier=self.supplier,
            operation_key=uuid4(), reference="Compra HTTP", items=[dict(product=self.product,
                quantity="3.000", unit_cost="5.25", lot_code="LOTE-COMPRA", expires_on=None)])

    def purchase_data(self):
        data = {"operation_key": str(uuid4()), "supplier": self.supplier.pk, "reference": "NF-HTTP-01",
            "purchased_on": timezone.localdate().isoformat(), "notes": "Conferir entrega",
            "items-TOTAL_FORMS": "2", "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "1", "items-MAX_NUM_FORMS": "30"}
        for index, product in enumerate([self.product, self.second_product]):
            data.update({f"items-{index}-product": product.pk, f"items-{index}-quantity": "2.500",
                f"items-{index}-unit_cost": "12.20", f"items-{index}-lot_code": f"LOTE-{index}", f"items-{index}-expires_on": ""})
        return data

    def test_all_primary_pages_and_forms_render_with_private_cache_and_distinct_tabs(self):
        for name in ["overview", "lots", "purchases", "movements", "assets", "catalog", "product_create", "movement_create",
                     "purchase_create", "asset_create", "category_create", "supplier_create"]:
            with self.subTest(name=name):
                response = self.client.get(self.url(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertContains(response, "Estoque e patrimônio")

    def test_detail_and_correction_pages_render(self):
        entry = self.entry()
        purchase = self.purchase()
        asset = save_record(instance=Asset(organization=self.org, code="BEM-1", name="Computador", custodian=self.owner), actor=self.owner, reason="Cadastro inicial")
        for name, pk in [("product_detail", self.product.pk), ("product_edit", self.product.pk),
                         ("product_movement", self.product.pk), ("movement_reverse", entry.pk),
                         ("purchase_detail", purchase.pk), ("purchase_cancel", purchase.pk),
                         ("asset_detail", asset.pk), ("asset_edit", asset.pk),
                         ("category_edit", self.category.pk), ("supplier_edit", self.supplier.pk)]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name, pk)).status_code, 200)
        self.assertEqual(Movement.objects.count(), 1)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, "draft")

    def test_only_direction_and_management_enter_inventory(self):
        for role in ["operator", "viewer", "client"]:
            self.client.force_login(self.users[role])
            for name in ["overview", "assets", "purchases", "movements", "catalog", "product_create"]:
                self.assertEqual(self.client.get(self.url(name)).status_code, 403, (role, name))
            self.assertEqual(self.client.post(self.url("product_create"), {"name": "Proibido"}).status_code, 403)
        self.client.force_login(self.users["manager"])
        self.assertEqual(self.client.get(self.url("overview")).status_code, 200)

    def test_anonymous_redirect_and_revoked_membership_denied(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url("overview")).status_code, 302)
        self.client.force_login(self.owner)
        Membership.objects.filter(user=self.owner, organization=self.org).update(is_active=False)
        self.assertEqual(self.client.get(self.url("overview")).status_code, 403)

    def test_max_plan_and_active_subscription_required_on_writes(self):
        self.subscription.plan = "start"
        self.subscription.save()
        self.assertEqual(self.client.get(self.url("overview")).status_code, 403)
        self.assertEqual(self.client.post(self.url("product_create"), {"name": "Não criar"}).status_code, 403)
        self.subscription.plan, self.subscription.status = "max", "suspended"
        self.subscription.save()
        self.assertRedirects(self.client.post(self.url("purchase_create"), self.purchase_data()), reverse("billing:subscription"))
        self.assertFalse(Purchase.objects.exists())

    def test_cross_office_object_identifiers_never_reveal_details(self):
        foreign_entry = self.entry(self.foreign_product, self.outsider, self.foreign)
        foreign_purchase = create_purchase(organization=self.foreign, actor=self.outsider, operation_key=uuid4(),
            items=[dict(product=self.foreign_product, quantity="1", unit_cost="1", lot_code="FOREIGN", expires_on=None)])
        foreign_asset = save_record(instance=Asset(organization=self.foreign, code="F-1", name="Bem externo"), actor=self.outsider)
        for name, pk in [("product_detail", self.foreign_product.pk), ("product_edit", self.foreign_product.pk),
                         ("product_movement", self.foreign_product.pk), ("movement_reverse", foreign_entry.pk),
                         ("purchase_detail", foreign_purchase.pk), ("purchase_receive", foreign_purchase.pk),
                         ("purchase_cancel", foreign_purchase.pk), ("asset_detail", foreign_asset.pk),
                         ("asset_edit", foreign_asset.pk), ("category_edit", self.foreign_category.pk)]:
            with self.subTest(name=name):
                method = self.client.post if name == "purchase_receive" else self.client.get
                self.assertEqual(method(self.url(name, pk)).status_code, 404)
        response = self.client.get(self.url("overview"), {"q": "confidencial"})
        self.assertNotContains(response, self.foreign_product.name)

    def test_product_creation_is_tenant_scoped_and_foreign_category_rejected(self):
        data = {"organization": self.foreign.pk, "code": "NEW-HTTP", "name": "Novo material", "unit": "un",
            "category": self.foreign_category.pk, "location": "Armário", "minimum_stock": "2", "is_active": "on"}
        response = self.client.post(self.url("product_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(Product.objects.filter(code="NEW-HTTP").exists())
        data["category"] = self.category.pk
        response = self.client.post(self.url("product_create"), data)
        product = Product.objects.get(code="NEW-HTTP")
        self.assertEqual(product.organization_id, self.org.pk)
        self.assertRedirects(response, self.url("product_detail", product.pk))
        self.assertEqual(product.current_stock, 0)

    def test_movement_route_pins_product_and_rejects_foreign_lot(self):
        foreign_entry = self.entry(self.foreign_product, self.outsider, self.foreign)
        data = {"operation_key": str(uuid4()), "product": self.foreign_product.pk, "kind": "consumption",
            "lot": foreign_entry.lot_id, "quantity": "1", "reason": "Tentativa de lote externo"}
        response = self.client.post(self.url("product_movement", self.product.pk), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("lot", response.context["form"].errors)
        data.update({"kind": "entry", "lot": "", "lot_code": "LOCAL", "reason": "Entrada local"})
        response = self.client.post(self.url("product_movement", self.product.pk), data)
        self.assertRedirects(response, self.url("product_detail", self.product.pk))
        self.assertEqual(Movement.objects.get(organization=self.org).product_id, self.product.pk)

    def test_http_movement_repeat_and_insufficient_balance_have_no_extra_writes(self):
        data = {"operation_key": str(uuid4()), "kind": "entry", "lot_code": "HTTP-REPEAT", "quantity": "5", "reason": "Conferência"}
        url = self.url("product_movement", self.product.pk)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(Movement.objects.count(), 1)
        lot = StockLot.objects.get(organization=self.org)
        data.update({"operation_key": str(uuid4()), "kind": "consumption", "lot": lot.pk, "lot_code": "", "quantity": "6"})
        response = self.client.post(url, data)
        self.assertContains(response, "Saldo insuficiente")
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, Decimal("5"))

    def test_reversal_get_only_previews_then_post_compensates(self):
        entry = self.entry()
        url = self.url("movement_reverse", entry.pk)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(Movement.objects.count(), 1)
        data = {"reason": "Entrada registrada por engano", "operation_key": str(uuid4())}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(Movement.objects.count(), 2)
        self.assertEqual(self.product.current_stock, 0)

    def test_purchase_multiline_receipt_requires_explicit_confirmation_and_is_idempotent(self):
        data = self.purchase_data()
        response = self.client.post(self.url("purchase_create"), data)
        purchase = Purchase.objects.get(organization=self.org)
        self.assertRedirects(response, self.url("purchase_detail", purchase.pk))
        self.assertEqual(purchase.items.count(), 2)
        self.assertEqual(purchase.total, Decimal("61.00"))
        self.assertFalse(Movement.objects.exists())
        self.assertEqual(self.client.post(self.url("purchase_create"), data).status_code, 302)
        self.assertEqual(Purchase.objects.count(), 1)
        receipt = self.url("purchase_receive", purchase.pk)
        self.assertEqual(self.client.get(receipt).status_code, 405)
        response = self.client.post(receipt, {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["receipt_form"].errors)
        self.assertFalse(Movement.objects.exists())
        for _ in range(2):
            self.assertEqual(self.client.post(receipt, {"confirmed": "on"}).status_code, 302)
        self.assertEqual(Movement.objects.count(), 2)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, "received")

    def test_purchase_invalid_line_and_foreign_product_do_not_create_partial_purchase(self):
        data = self.purchase_data()
        data["items-1-product"] = self.foreign_product.pk
        response = self.client.post(self.url("purchase_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["item_forms"].errors)
        self.assertFalse(Purchase.objects.exists())
        self.assertFalse(Movement.objects.exists())
        data["items-1-product"] = self.second_product.pk
        data["items-1-quantity"] = "-1"
        self.assertEqual(self.client.post(self.url("purchase_create"), data).status_code, 200)
        self.assertFalse(Purchase.objects.exists())

    def test_purchase_cancel_preserves_items_and_receipt_refuses_cancelled_purchase(self):
        purchase = self.purchase()
        response = self.client.post(self.url("purchase_cancel", purchase.pk), {"reason": "Fornecedor cancelou a entrega"})
        self.assertRedirects(response, self.url("purchase_detail", purchase.pk))
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, "cancelled")
        self.assertEqual(purchase.items.count(), 1)
        self.assertEqual(self.client.post(self.url("purchase_receive", purchase.pk), {"confirmed": "on"}).status_code, 200)
        self.assertFalse(Movement.objects.exists())

    def test_asset_creation_and_transfer_record_human_readable_immutable_history(self):
        data = {"code": "BEM-HTTP", "name": "Notebook", "serial_number": "SER-123", "category": self.category.pk,
            "location": "Recepção", "custodian": self.owner.pk, "acquired_on": timezone.localdate().isoformat(),
            "acquisition_value": "3500.00", "status": "available", "notes": "Etiqueta aplicada", "reason": "Inventário inicial"}
        response = self.client.post(self.url("asset_create"), data)
        asset = Asset.objects.get(code="BEM-HTTP")
        self.assertRedirects(response, self.url("asset_detail", asset.pk))
        first = AssetEvent.objects.get(asset=asset)
        data.update({"custodian": self.users["operator"].pk, "location": "Sala de atendimento", "status": "in_use", "reason": "Entrega para atendimento"})
        response = self.client.post(self.url("asset_edit", asset.pk), data)
        self.assertRedirects(response, self.url("asset_detail", asset.pk))
        self.assertEqual(AssetEvent.objects.filter(asset=asset).count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.after["location"], "Recepção")
        response = self.client.get(self.url("asset_detail", asset.pk))
        self.assertContains(response, "Em uso")
        self.assertContains(response, "Responsável")
        self.assertNotContains(response, "custodian_id")

    def test_asset_custodian_must_be_current_internal_member(self):
        data = {"code": "REJECTED", "name": "Equipamento", "status": "available", "reason": "Cadastro",
            "custodian": self.users["client"].pk}
        response = self.client.post(self.url("asset_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("custodian", response.context["form"].errors)
        self.assertFalse(Asset.objects.exists())

    def test_stock_search_filter_and_expiry_summary_ignore_depleted_lots(self):
        entry = self.entry(expires_on=timezone.localdate() + timedelta(days=3))
        response = self.client.get(self.url("overview"), {"q": "Papel", "status": "low"})
        self.assertEqual(response.context["page"].paginator.count, 0)
        self.assertEqual(response.context["summary"]["expiring_count"], 1)
        record_movement(organization=self.org, actor=self.owner, product=self.product, kind="consumption", lot=entry.lot,
            quantity="12", reason="Uso interno", operation_key=uuid4())
        response = self.client.get(self.url("overview"), {"q": "Papel", "status": "low"})
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertEqual(response.context["summary"]["expiring_count"], 0)

    def test_write_forms_keep_csrf_protection(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.post(self.url("product_create"), {"name": "Sem CSRF"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Product.objects.filter(name="Sem CSRF").exists())

    def test_lot_filters_show_all_matching_alerts_without_cross_tenant_records(self):
        expired = self.entry(expires_on=timezone.localdate() - timedelta(days=1))
        self.entry(self.foreign_product, self.outsider, self.foreign, expires_on=timezone.localdate() - timedelta(days=1))
        response = self.client.get(self.url("lots"), {"status": "expired"})
        self.assertEqual(response.context["page"].paginator.count, 1)
        self.assertContains(response, self.product.name)
        self.assertNotContains(response, self.foreign_product.name)
        self.assertEqual(self.client.get(self.url("lots"), {"status": "soon"}).context["page"].paginator.count, 0)
        record_movement(organization=self.org, actor=self.owner, product=self.product, kind="loss", lot=expired.lot,
            quantity="12", reason="Baixa do material vencido", operation_key=uuid4())
        self.assertEqual(self.client.get(self.url("lots"), {"status": "expired"}).context["page"].paginator.count, 0)
        self.assertEqual(self.client.get(self.url("lots"), {"status": "empty"}).context["page"].paginator.count, 1)

    def test_stored_text_is_escaped_in_catalog_and_asset_history(self):
        Supplier.objects.create(organization=self.org, name='<script>alert("supplier")</script>')
        response = self.client.get(self.url("catalog"))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("supplier")</script>')
