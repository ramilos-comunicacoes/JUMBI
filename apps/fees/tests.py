from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.models import AuditEvent, Contact, FinanceEntry, Matter, Payment
from apps.legal.services import record_payment, reverse_payment
from .models import FeeInstallment, FeePlan, validate_fee_entry
from .services import build_schedule, create_plan, installment_rows, visible_plans


class ScheduleTests(SimpleTestCase):
    def schedule(self, **kwargs):
        payload = {"kind": "installments", "amount": "100.00", "periods": 3, "first_due_date": date(2028, 1, 31)}
        payload.update(kwargs)
        return build_schedule(**payload)

    def test_cent_exact_split_and_leap_year_month_end(self):
        rows = self.schedule()
        self.assertEqual([row["amount"] for row in rows], [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")])
        self.assertEqual([row["due_date"] for row in rows], [date(2028, 1, 31), date(2028, 2, 29), date(2028, 3, 31)])
        self.assertEqual(sum(row["amount"] for row in rows), Decimal("100.00"))

    def test_anchor_day_restored_after_short_month_and_year_rollover(self):
        rows = self.schedule(first_due_date=date(2027, 12, 30), periods=4)
        self.assertEqual([row["due_date"] for row in rows], [date(2027, 12, 30), date(2028, 1, 30), date(2028, 2, 29), date(2028, 3, 30)])

    def test_monthly_amount_is_per_month_and_horizon_finite(self):
        rows = self.schedule(kind="monthly", amount="89.90", periods=36, first_due_date=date(2026, 4, 30))
        self.assertEqual(len(rows), 36)
        self.assertEqual(rows[1]["due_date"], date(2026, 5, 31))
        self.assertEqual(sum(row["amount"] for row in rows), Decimal("3236.40"))

    def test_invalid_values_never_round_or_create_zero_installments(self):
        cases = [{"amount": value} for value in [0, -1, "NaN", "Infinity", "0.001", 1.23, True, "1000000000000"]]
        cases += [{"periods": value} for value in [0, 37, True, "3"]]
        cases += [{"amount": "0.02", "periods": 3}, {"kind": "client_fund"}, {"first_due_date": "2026-01-01"}, {"first_due_date": date(9999, 12, 31)}, {"amount": "999999999999.99", "kind": "monthly"}]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                self.schedule(**payload)


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class FeePlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Honorários teste", slug="fees-test", business_type="office")
        cls.other = Organization.objects.create(name="Outro escritório", slug="fees-other", business_type="office")
        users = {}
        for role in ["owner", "manager", "operator", "viewer", "client"]:
            users[role] = get_user_model().objects.create_user(email=f"fees-{role}@example.test", password="fees-test-only")
            Membership.objects.create(user=users[role], organization=cls.org, role=role)
        cls.owner, cls.manager, cls.operator, cls.viewer, cls.client_user = [users[role] for role in ["owner", "manager", "operator", "viewer", "client"]]
        cls.outsider = get_user_model().objects.create_user(email="fees-outsider@example.test", password="fees-test-only")
        Membership.objects.create(user=cls.outsider, organization=cls.other, role="owner")
        cls.contact = Contact.objects.create(organization=cls.org, name="Cliente de teste")
        cls.other_contact = Contact.objects.create(organization=cls.other, name="Cliente externo")
        cls.unrelated_contact = Contact.objects.create(organization=cls.org, name="Outro cliente local")
        cls.matter = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Pasta visível")
        cls.secret = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Pasta sigilosa", confidential=True)
        cls.other_matter = Matter.objects.create(organization=cls.other, owner=cls.outsider, client=cls.other_contact, title="Pasta externa")

    def setUp(self):
        self.client.force_login(self.owner)

    def create(self, **kwargs):
        payload = dict(organization=self.org, actor=self.owner, matter=self.matter, client=self.contact, title="Honorários acordados", kind="installments", amount="100.00", periods=3, first_due_date=date(2028, 1, 31), operation_key=uuid4(), notes="Condições conferidas")
        payload.update(kwargs)
        return create_plan(**payload)

    def form_data(self, **kwargs):
        payload = {"operation_key": str(uuid4()), "matter": str(self.matter.pk), "client": str(self.contact.pk), "title": "Acordo pela tela", "kind": "installments", "amount": "100.00", "periods": "3", "first_due_date": "2028-01-31", "notes": "", "action": "preview"}
        payload.update(kwargs)
        return payload

    def test_plan_creates_income_only_and_finance_ledger_once(self):
        key = uuid4()
        plan = self.create(operation_key=key)
        retry = self.create(operation_key=key)
        self.assertEqual(plan.pk, retry.pk)
        self.assertEqual(FeePlan.objects.count(), 1)
        self.assertEqual(FeeInstallment.objects.count(), 3)
        self.assertEqual(FinanceEntry.objects.count(), 3)
        self.assertEqual(AuditEvent.objects.filter(action="fees.plan_created").count(), 1)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(FinanceEntry.objects.exclude(kind="income").exists())
        self.assertEqual(plan.total_amount, Decimal("100.00"))
        self.assertTrue(all(item.entry.matter_id == self.matter.pk for item in plan.installments.all()))

    def test_key_collision_with_changed_payload_rejected(self):
        key = uuid4()
        self.create(operation_key=key)
        for change in [{"amount": "101.00"}, {"notes": "Mudança"}, {"actor": self.manager}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.create(operation_key=key, **change)
        self.assertEqual(FinanceEntry.objects.count(), 3)

    def test_partial_payment_and_reversal_remain_consistent(self):
        plan = self.create()
        entry = plan.installments.first().entry
        payment = record_payment(entry=entry, actor=self.owner, amount="10.00", note="Parcial")
        rows = installment_rows(plan)
        self.assertTrue(rows.ordered)
        self.assertEqual([item.number for item in rows], [1, 2, 3])
        self.assertEqual([item.net_paid for item in rows], [Decimal("10.00"), Decimal("0.00"), Decimal("0.00")])
        row = list(rows)[0]
        self.assertEqual(row.entry_id, entry.pk)
        self.assertEqual(row.net_paid, Decimal("10.00"))
        self.assertEqual(row.remaining, Decimal("23.34"))
        response = self.client.get(reverse("fees:detail", args=[plan.pk]))
        self.assertEqual(response.context["balance"], Decimal("90.00"))
        reverse_payment(payment=payment, actor=self.owner, note="Baixa duplicada")
        row = list(installment_rows(plan))[0]
        self.assertEqual(row.net_paid, Decimal("0.00"))
        self.assertEqual(row.remaining, Decimal("33.34"))
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(FeeInstallment.objects.count(), 3)

    def test_permissions_tenant_confidential_client_and_revocation(self):
        for actor in [self.operator, self.viewer, self.client_user, self.outsider]:
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                self.create(actor=actor)
        with self.assertRaises(PermissionDenied):
            self.create(actor=self.manager, matter=self.secret)
        with self.assertRaises(PermissionDenied):
            self.create(matter=self.other_matter)
        for contact in [self.other_contact, self.unrelated_contact]:
            with self.assertRaises(ValidationError):
                self.create(client=contact)
        self.create(actor=self.manager)
        Membership.objects.filter(user=self.manager, organization=self.org).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.create(actor=self.manager)

    def test_secret_plan_hidden_from_manager_even_with_direct_id(self):
        plan = self.create(matter=self.secret)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("fees:detail", args=[plan.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("fees:overview")), plan.title)
        self.secret.members.add(self.manager)
        self.assertEqual(self.client.get(reverse("fees:detail", args=[plan.pk])).status_code, 200)
        self.secret.members.remove(self.manager)
        self.assertFalse(visible_plans(self.manager, self.org).exists())

    def test_other_tenant_and_low_privilege_direct_views(self):
        plan = self.create()
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("fees:detail", args=[plan.pk])).status_code, 404)
        for user in [self.operator, self.viewer, self.client_user]:
            self.client.force_login(user)
            for name in ["overview", "create"]:
                self.assertEqual(self.client.get(reverse(f"fees:{name}")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("fees:overview")).status_code, 302)

    def test_preview_confirm_csrf_and_no_create_on_get(self):
        data = self.form_data()
        self.assertEqual(self.client.get(reverse("fees:create")).status_code, 200)
        response = self.client.post(reverse("fees:create"), data)
        self.assertContains(response, "33,34")
        self.assertContains(response, "29/02/2028")
        self.assertFalse(FeePlan.objects.exists())
        data["action"] = "create"
        self.assertContains(self.client.post(reverse("fees:create"), data), "marque a confirmação")
        self.assertFalse(FeePlan.objects.exists())
        data["reviewed"] = "on"
        self.assertEqual(self.client.post(reverse("fees:create"), data).status_code, 302)
        self.assertEqual(self.client.post(reverse("fees:create"), data).status_code, 302)
        self.assertEqual(FeePlan.objects.count(), 1)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(reverse("fees:create"), data).status_code, 403)

    def test_form_rejects_foreign_identifiers_and_escapes_notes(self):
        response = self.client.post(reverse("fees:create"), self.form_data(matter=self.other_matter.pk, client=self.other_contact.pk, action="create", reviewed="on"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(FeePlan.objects.exists())
        plan = self.create(notes="<script>alert(1)</script>")
        response = self.client.get(reverse("fees:detail", args=[plan.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_atomic_rollback_when_an_installment_cannot_be_created(self):
        with patch("apps.fees.services.FeeInstallment.objects.create", side_effect=ValidationError("Failure")):
            with self.assertRaises(ValidationError):
                self.create()
        self.assertFalse(FeePlan.objects.exists())
        self.assertFalse(FinanceEntry.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action="fees.plan_created").exists())

    def test_immutable_plan_installment_and_original_ledger(self):
        plan = self.create()
        item = plan.installments.first()
        for mutation in [lambda: plan.delete(), lambda: FeePlan.objects.filter(pk=plan.pk).update(title="Changed"), lambda: item.delete(), lambda: FeeInstallment.objects.all().delete()]:
            with self.assertRaises(ValidationError):
                mutation()
        plan.title = "Changed"
        with self.assertRaises(ValidationError):
            plan.save()
        entry = item.entry
        for field, value in [("amount", Decimal("20.00")), ("due_date", date(2028, 2, 1)), ("kind", "client_fund"), ("matter", self.secret)]:
            entry.refresh_from_db()
            setattr(entry, field, value)
            with self.assertRaises(ValidationError):
                validate_fee_entry(entry)
            with self.assertRaises(ValidationError):
                entry.save()

    @override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
    def test_max_required_and_historical_export_after_expiration(self):
        subscription = OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
        with self.assertRaises(PermissionDenied):
            self.create()
        self.assertEqual(self.client.get(reverse("fees:overview")).status_code, 403)
        subscription.plan = "max"
        subscription.save()
        plan = self.create()
        self.assertEqual(self.client.get(reverse("fees:detail", args=[plan.pk])).status_code, 200)
        subscription.expires_at = timezone.now() - timedelta(days=1)
        subscription.save()
        with self.assertRaises(PermissionDenied):
            self.create()
        self.assertFalse(visible_plans(self.owner, self.org).exists())
        self.assertTrue(visible_plans(self.owner, self.org, for_export=True).filter(pk=plan.pk).exists())


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class FeeConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_duplicate_concurrent_requests_create_one_plan_and_one_schedule(self):
        organization = Organization.objects.create(name="Concorrência", slug="fees-concurrency", business_type="office")
        actor = get_user_model().objects.create_user(email="fees-concurrency@example.test")
        Membership.objects.create(organization=organization, user=actor, role="owner")
        client = Contact.objects.create(organization=organization, name="Cliente")
        matter = Matter.objects.create(organization=organization, owner=actor, client=client, title="Pasta")
        key, barrier = uuid4(), Barrier(2)

        def worker():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return create_plan(organization=organization, actor=actor, matter=matter, client=client, title="Pedido simultâneo", kind="installments", amount="100.00", periods=3, first_due_date=date(2028, 1, 31), operation_key=key).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = [future.result(timeout=20) for future in [pool.submit(worker), pool.submit(worker)]]
        self.assertEqual(first, second)
        self.assertEqual(FeePlan.objects.count(), 1)
        self.assertEqual(FeeInstallment.objects.count(), 3)
        self.assertEqual(FinanceEntry.objects.count(), 3)
        self.assertEqual(AuditEvent.objects.filter(action="fees.plan_created").count(), 1)
