from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.models import AuditEvent, FinanceEntry, Payment
from .management.commands.seed_inventory_demo import ACTION, ASSET_CODES, CATEGORY_NAME, DEMO_TARGETS, PRODUCT_CODES, PURCHASE_REFERENCE, SUPPLIER_NAME, operation_key
from .models import Asset, AssetEvent, Category, Movement, Product, Purchase, PurchaseItem, StockLot, Supplier
from .services import record_movement, save_record, stock_summary


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
class InventoryDemoCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Demonstração de teste", slug="jumbi-demonstracao-local", business_type="office")
        cls.actor = get_user_model().objects.create_user(email="demo@jumbi.local")
        cls.membership = Membership.objects.create(organization=cls.organization, user=cls.actor, role="manager")
        cls.subscription = OrganizationSubscription.objects.create(organization=cls.organization, plan="max", status="demo")

    def command(self, *, apply=False, **overrides):
        arguments = dict(organization=self.organization.slug, email=self.actor.email, apply=apply, stdout=StringIO())
        arguments.update(overrides)
        call_command("seed_inventory_demo", **arguments)
        return arguments["stdout"].getvalue()

    def counts(self):
        return {model._meta.model_name: model.objects.count() for model in [Category, Supplier, Product, StockLot, Movement, Purchase, PurchaseItem, Asset, AssetEvent, AuditEvent, FinanceEntry, Payment]}

    def test_default_preview_does_not_write_any_records(self):
        before = self.counts()
        output = self.command()
        self.assertIn("PRÉVIA", output)
        self.assertIn("2 materiais", output)
        self.assertEqual(self.counts(), before)

    def test_apply_creates_labeled_samples_with_one_low_stock_and_no_finance(self):
        output = self.command(apply=True)
        self.assertIn("Demonstração cadastrada", output)
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(StockLot.objects.count(), 2)
        self.assertEqual(Movement.objects.count(), 2)
        self.assertEqual(PurchaseItem.objects.count(), 2)
        self.assertEqual(Asset.objects.count(), 2)
        self.assertEqual(AssetEvent.objects.count(), 2)
        self.assertEqual(Product.objects.get(code="DEMO-PAPEL").current_stock, Decimal("10"))
        self.assertEqual(Product.objects.get(code="DEMO-TONER").current_stock, Decimal("1"))
        summary = stock_summary(self.actor, self.organization)
        self.assertEqual(summary["low_stock_count"], 1)
        self.assertEqual(summary["maintenance_count"], 1)
        self.assertEqual(Purchase.objects.get().status, "draft")
        self.assertEqual(Purchase.objects.get().total, Decimal("510.00"))
        for model in [Category, Supplier, Product, Asset]:
            self.assertFalse(model.objects.exclude(name__startswith="[DEMONSTRAÇÃO]").exists())
        self.assertFalse(Movement.objects.exclude(reason__startswith="[DEMONSTRAÇÃO]").exists())
        self.assertEqual(AuditEvent.objects.filter(action=ACTION).count(), 1)
        self.assertFalse(FinanceEntry.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_rerun_and_preview_preserve_manual_consumption_and_edits(self):
        self.command(apply=True)
        product = Product.objects.get(code="DEMO-PAPEL")
        record_movement(organization=self.organization, actor=self.actor, product=product, lot=product.lots.get(), kind="consumption", quantity="4", reason="Teste manual posterior", operation_key=uuid4())
        asset = Asset.objects.get(code="DEMO-NOTEBOOK")
        asset.location = "Sala alterada manualmente"
        save_record(instance=asset, actor=self.actor, reason="Teste manual")
        before = self.counts()
        for apply in (False, True):
            self.assertIn("já cadastrados", self.command(apply=apply))
            self.assertEqual(self.counts(), before)
        self.assertEqual(product.current_stock, Decimal("6"))
        asset.refresh_from_db()
        self.assertEqual(asset.location, "Sala alterada manualmente")

    def test_exact_allowlist_refuses_real_office_wrong_email_and_mixed_pairs(self):
        before = self.counts()
        for args in [dict(organization="escritorio-real"), dict(email="admin@jumbi.nabio.pro"), dict(organization="jumbi-demonstracao", email="demo@jumbi.local"), dict(organization="JUMBI-DEMONSTRACAO-LOCAL")]:
            with self.subTest(args=args), self.assertRaises(CommandError):
                self.command(apply=True, **args)
        self.assertEqual(self.counts(), before)

    def test_production_demo_pair_is_allowed_only_with_its_own_membership(self):
        organization = Organization.objects.create(name="Outra demonstração", slug="jumbi-demonstracao", business_type="office")
        actor = get_user_model().objects.create_user(email=DEMO_TARGETS[organization.slug])
        OrganizationSubscription.objects.create(organization=organization, plan="max", status="demo")
        with self.assertRaises(CommandError):
            self.command(apply=True, organization=organization.slug, email=actor.email)
        Membership.objects.create(organization=organization, user=actor, role="manager")
        self.command(apply=True, organization=organization.slug, email=actor.email)
        self.assertEqual(Product.objects.filter(organization=organization).count(), 2)
        self.assertFalse(Product.objects.filter(organization=self.organization).exists())

    def test_real_plan_expired_demo_inactive_org_and_other_segment_are_rejected(self):
        before = self.counts()
        for change in [dict(status="active"), dict(plan="start"), dict(expires_at=timezone.now() - timedelta(days=1))]:
            original = {key: getattr(self.subscription, key) for key in change}
            for key, value in change.items():
                setattr(self.subscription, key, value)
            self.subscription.save()
            with self.subTest(change=change), self.assertRaises(CommandError):
                self.command(apply=True)
            for key, value in original.items():
                setattr(self.subscription, key, value)
            self.subscription.save()
        for change in [dict(status="suspended"), dict(business_type="other")]:
            Organization.objects.filter(pk=self.organization.pk).update(**change)
            with self.subTest(change=change), self.assertRaises(CommandError):
                self.command(apply=True)
            Organization.objects.filter(pk=self.organization.pk).update(status="active", business_type="office")
        self.assertEqual(self.counts(), before)

    def test_inactive_user_revoked_membership_and_operator_are_rejected(self):
        for change in [dict(is_active=False), dict(role="operator"), dict(role="client")]:
            Membership.objects.filter(pk=self.membership.pk).update(**change)
            with self.subTest(change=change), self.assertRaises(CommandError):
                self.command(apply=True)
            Membership.objects.filter(pk=self.membership.pk).update(is_active=True, role="manager")
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
        with self.assertRaises(CommandError):
            self.command(apply=True)
        self.assertFalse(Product.objects.exists())

    def test_existing_material_code_is_never_overwritten_or_partially_completed(self):
        real = Product.objects.create(organization=self.organization, code=PRODUCT_CODES[1], name="Material cadastrado manualmente", minimum_stock="15")
        before = self.counts()
        for apply in (False, True):
            with self.subTest(apply=apply), self.assertRaises(CommandError):
                self.command(apply=apply)
        self.assertEqual(self.counts(), before)
        real.refresh_from_db()
        self.assertEqual(real.name, "Material cadastrado manualmente")
        self.assertEqual(real.minimum_stock, 15)

    def test_category_supplier_or_asset_conflicts_do_not_create_any_other_records(self):
        constructors = [
            lambda: Category.objects.create(organization=self.organization, name=CATEGORY_NAME),
            lambda: Supplier.objects.create(organization=self.organization, name=SUPPLIER_NAME),
            lambda: save_record(instance=Asset(organization=self.organization, code=ASSET_CODES[0], name="Notebook real"), actor=self.actor),
        ]
        for constructor in constructors:
            with self.subTest(constructor=constructor):
                with self.captureOnCommitCallbacks():
                    # A nested rollback isolates each conflict without deleting history.
                    from django.db import transaction
                    with transaction.atomic():
                        constructor()
                        before = self.counts()
                        with self.assertRaises(CommandError):
                            self.command(apply=True)
                        self.assertEqual(self.counts(), before)
                        transaction.set_rollback(True)

    def test_late_failure_rolls_back_every_record_and_marker(self):
        before = self.counts()
        with patch("apps.inventory.management.commands.seed_inventory_demo.audit", side_effect=ValidationError("Falha ao registrar conclusão")):
            with self.assertRaises(CommandError):
                self.command(apply=True)
        self.assertEqual(self.counts(), before)
        self.assertFalse(AuditEvent.objects.filter(action=ACTION).exists())

    def test_operation_ids_are_stable_and_differ_between_demo_offices(self):
        self.assertEqual(operation_key("jumbi-demonstracao", "DEMO-PAPEL"), operation_key("jumbi-demonstracao", "DEMO-PAPEL"))
        self.assertNotEqual(operation_key("jumbi-demonstracao", "DEMO-PAPEL"), operation_key("jumbi-demonstracao-local", "DEMO-PAPEL"))
        self.command(apply=True)
        self.assertEqual(set(Movement.objects.values_list("operation_key", flat=True)), {operation_key(self.organization.slug, code) for code in PRODUCT_CODES})
        self.assertEqual(Purchase.objects.get().operation_key, operation_key(self.organization.slug, "purchase"))
