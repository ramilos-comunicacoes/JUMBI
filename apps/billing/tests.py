import hashlib
import io
import json
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, transaction
from django.test import Client as HttpClient, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from apps.core.models import Membership, Organization, User, WorkspaceInvitation
from apps.legal.models import Contact, Document, DocumentVersion, FinanceEntry, Matter, Opportunity, Payment
from apps.legal.services import add_document_version, record_payment
from .admin import SubscriptionForm
from .models import OrganizationSubscription, SubscriptionEvent
from .plans import PLAN_CHOICES, PLANS
from .services import check_capacity, require_access, usage, validate_plan_change


BILLING_TEST_SETTINGS = {
    "JUMBI_ENFORCE_SUBSCRIPTIONS": True, "DEBUG": True, "SECURE_SSL_REDIRECT": False,
    "ALLOWED_HOSTS": ["testserver"],
    "STORAGES": {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                 "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
}


@override_settings(**BILLING_TEST_SETTINGS)
class BillingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner@billing.test", "TestOnlyPass!2026")
        cls.org = Organization.objects.create(name="Escritório contratante", slug="contratante", business_type="office")
        cls.membership = Membership.objects.create(organization=cls.org, user=cls.owner, role="owner")
        cls.subscription = OrganizationSubscription.objects.create(organization=cls.org, status="active", plan="start")
        cls.contact = Contact.objects.create(organization=cls.org, name="Pessoa cliente")
        cls.matter = Matter.objects.create(organization=cls.org, owner=cls.owner, title="Pasta atual")
        cls.entry = FinanceEntry.objects.create(organization=cls.org, matter=cls.matter, description="Honorários",
                                                amount=Decimal("100.00"), due_date=timezone.localdate())
        cls.opportunity = Opportunity.objects.create(organization=cls.org, contact=cls.contact, owner=cls.owner, title="Proposta")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.owner)

    def set_subscription(self, **values):
        OrganizationSubscription.objects.filter(pk=self.subscription.pk).update(**values)
        self.subscription.refresh_from_db()

    def matter_data(self, title="Nova pasta", status="active"):
        return {"title": title, "nature": "advisory", "status": status, "owner": self.owner.pk}

    def invitation(self, email, token="billing-invitation"):
        return WorkspaceInvitation.objects.create(
            organization=self.org, email=email, role="viewer", invited_by=self.owner,
            token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=timezone.now() + timedelta(days=1),
        )

    def export_records(self):
        response = self.client.get(reverse("legal:export"))
        self.assertEqual(response.status_code, 200)
        payload = b"".join(response.streaming_content)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return json.loads(archive.read("records.json")), json.loads(archive.read("manifest.json"))

    def test_public_paid_signup_stays_pending_without_automatic_access(self):
        self.client.logout()
        response = self.client.post(reverse("core:signup"), {
            "first_name": "Cliente pagante", "email": "new@billing.test", "organization_name": "Escritório novo",
            "plan": "max", "password1": "TestOnlyPass!2026", "password2": "TestOnlyPass!2026",
        })
        self.assertRedirects(response, reverse("billing:subscription"))
        new_user = User.objects.get(email="new@billing.test")
        subscription = OrganizationSubscription.objects.get(organization__memberships__user=new_user)
        self.assertEqual((subscription.plan, subscription.status), ("max", "pending"))
        self.assertFalse(subscription.is_available)
        self.assertEqual(subscription.events.count(), 1)
        self.assertFalse(new_user.is_superuser)
        self.assertRedirects(self.client.get(reverse("legal:dashboard")), reverse("billing:subscription"))
        self.assertFalse(Payment.objects.exists())

    def test_signup_requires_a_known_paid_plan(self):
        self.client.logout()
        response = self.client.post(reverse("core:signup"), {
            "first_name": "Pessoa", "email": "invalid-plan@billing.test", "organization_name": "Outro escritório",
            "plan": "free", "password1": "TestOnlyPass!2026", "password2": "TestOnlyPass!2026",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="invalid-plan@billing.test").exists())

    def test_start_blocks_direct_finance_and_max_module_routes_get_and_post(self):
        routes = []
        for module, obj in [("finance", self.entry)]:
            routes += [reverse("legal:list", args=[module]), reverse("legal:create", args=[module]),
                       reverse("legal:edit", args=[module, obj.pk])]
        routes.append(reverse("legal:action", args=["finance", self.entry.pk, "payment"]))
        routes.extend(reverse(name) for name in ["fees:overview", "fees:create", "contracts:library", "contracts:template_create", "inventory:overview", "inventory:product_create", "inventory:asset_create", "portal:access_create", "portal:review_create"])
        for url in routes:
            for method in [self.client.get, self.client.post]:
                with self.subTest(url=url, method=method.__name__):
                    self.assertEqual(method(url).status_code, 403)
        with self.assertRaises(PermissionDenied):
            record_payment(entry=self.entry, actor=self.owner, amount="20.00")
        self.assertFalse(Payment.objects.exists())

    def test_start_includes_crm_create_edit_and_read_without_financial_effects(self):
        for url in [reverse("legal:list", args=["crm"]), reverse("legal:create", args=["crm"]), reverse("legal:edit", args=["crm", self.opportunity.pk])]:
            self.assertEqual(self.client.get(url).status_code, 200)
        dashboard = self.client.get(reverse("legal:dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertTrue(any(item["key"] == "crm" for item in dashboard.context["nav"]))
        self.assertTrue(dashboard.context["crm_summary"])
        data = {"contact": self.contact.pk, "title": "Atendimento incluído no Start", "stage": "new", "amount": "250.00", "owner": self.owner.pk, "next_action": "Agendar reunião", "lost_reason": ""}
        self.assertEqual(self.client.post(reverse("legal:create", args=["crm"]), data).status_code, 302)
        opportunity = Opportunity.objects.get(title=data["title"])
        data.update(stage="proposal", next_action="Aguardar proposta")
        self.assertEqual(self.client.post(reverse("legal:edit", args=["crm", opportunity.pk]), data).status_code, 302)
        opportunity.refresh_from_db()
        self.assertEqual(opportunity.stage, "proposal")
        self.assertEqual(opportunity.organization_id, self.org.pk)
        self.assertEqual(FinanceEntry.objects.count(), 1)
        self.assertFalse(Payment.objects.exists())

    def test_start_crm_keeps_readonly_profile_and_tenant_boundaries(self):
        other = Organization.objects.create(name="Outro escritório", slug="crm-other", business_type="office")
        outsider = User.objects.create_user("crm-other@billing.test")
        Membership.objects.create(organization=other, user=outsider, role="owner")
        other_contact = Contact.objects.create(organization=other, name="Pessoa externa")
        foreign = Opportunity.objects.create(organization=other, contact=other_contact, owner=outsider, title="Oportunidade externa")
        self.assertEqual(self.client.get(reverse("legal:edit", args=["crm", foreign.pk])).status_code, 404)
        response = self.client.post(reverse("legal:create", args=["crm"]), {"contact": other_contact.pk, "title": "Inválida", "stage": "new", "amount": "0", "owner": self.owner.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Opportunity.objects.filter(title="Inválida").exists())
        self.membership.role = "viewer"
        self.membership.save()
        self.assertEqual(self.client.get(reverse("legal:list", args=["crm"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("legal:create", args=["crm"])).status_code, 403)
        self.assertEqual(self.client.post(reverse("legal:edit", args=["crm", self.opportunity.pk]), {}).status_code, 403)

    def test_plan_catalog_uses_confirmed_prices_and_proportional_capacity(self):
        self.assertEqual((PLANS["start"]["price"], PLANS["start"]["members"], PLANS["start"]["matters"], PLANS["start"]["versions"]), (Decimal("299.90"), 5, 300, 1000))
        self.assertEqual((PLANS["max"]["price"], PLANS["max"]["members"], PLANS["max"]["matters"], PLANS["max"]["versions"]), (Decimal("599.90"), 20, 2000, 5000))
        self.assertEqual(dict(PLAN_CHOICES), {"start": "Start — R$ 299,90/mês", "max": "Max — R$ 599,90/mês"})
        self.subscription.refresh_from_db()
        self.assertEqual((self.subscription.plan, self.subscription.status), ("start", "active"))
        self.assertFalse(SubscriptionEvent.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_public_home_signup_and_platform_render_current_catalog_consistently(self):
        self.client.logout()
        home = self.client.get(reverse("core:home"))
        signup = self.client.get(reverse("core:signup"))
        for response in [home, signup]:
            self.assertEqual(response.status_code, 200)
            plain = " ".join(strip_tags(response.content.decode()).split())
            for price in ("299,90", "599,90"):
                self.assertIn(price, plain)
            for old in ("89,90", "199,90", "15 usuários", "100 pastas", "200 versões"):
                self.assertNotIn(old, plain)
        homepage = " ".join(strip_tags(home.content.decode()).split())
        for capacity in ("Até 5 usuários ativos", "300 pastas jurídicas ativas", "1.000 versões de documentos", "Até 20 usuários ativos", "2.000 pastas jurídicas ativas", "5.000 versões de documentos"):
            self.assertIn(capacity, homepage)
        self.assertIn("fichas completas, mapa por estado e CRM", homepage)
        self.assertEqual(list(signup.context["form"].fields["plan"].choices), PLAN_CHOICES)
        self.assertContains(signup, "Nenhuma cobrança automática")
        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(self.owner)
        platform = self.client.get(reverse("platform:office_create"))
        self.assertEqual(platform.status_code, 200)
        self.assertEqual(list(platform.context["form"].fields["plan"].choices), PLAN_CHOICES)
        self.assertContains(platform, "299,90")
        self.assertContains(platform, "599,90")
        self.assertContains(platform, "ativação é manual e não registra cobrança")
        self.assertFalse(SubscriptionEvent.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_subscription_and_upgrade_render_current_capacity_without_old_limits(self):
        for plan in ("start", "max"):
            self.set_subscription(plan=plan)
            response = self.client.get(reverse("billing:subscription"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, PLANS[plan]["price_label"])
            for key in ("members", "matters", "versions"):
                self.assertContains(response, f'max="{PLANS[plan][key]}"')
            self.assertContains(response, "Não há cobrança automática")
        self.set_subscription(plan="start")
        upgrade = self.client.get(reverse("legal:list", args=["finance"]))
        self.assertEqual(upgrade.status_code, 403)
        plain = " ".join(strip_tags(upgrade.content.decode()).split())
        for expected in ("599,90", "20 usuários", "2.000 pastas ativas", "5.000 versões de documentos"):
            self.assertIn(expected, plain)
        self.assertNotIn("15 usuários", plain)
        self.assertNotIn("1.000 pastas", plain)
        self.assertFalse(Payment.objects.exists())

    def test_max_grants_modules_but_does_not_override_membership_permissions(self):
        self.set_subscription(plan="max")
        for module in ["finance", "crm"]:
            self.assertEqual(self.client.get(reverse("legal:list", args=[module])).status_code, 200)
        self.membership.role = "viewer"
        self.membership.save()
        self.assertEqual(self.client.get(reverse("legal:list", args=["finance"])).status_code, 403)
        self.assertEqual(self.client.get(reverse("legal:create", args=["crm"])).status_code, 403)
        with self.assertRaises(PermissionDenied):
            record_payment(entry=self.entry, actor=self.owner, amount="20.00")

    def test_missing_pending_suspended_and_expired_subscriptions_redirect(self):
        protected = [reverse("legal:dashboard"), reverse("legal:create", args=["contacts"]), reverse("core:team"), reverse("core:audit")]
        for values in [{"status": "pending"}, {"status": "suspended"},
                       {"status": "active", "expires_at": timezone.now() - timedelta(seconds=1)}]:
            self.set_subscription(**values)
            for url in protected:
                with self.subTest(values=values, url=url):
                    self.assertRedirects(self.client.get(url), reverse("billing:subscription"))
            with self.assertRaises(PermissionDenied):
                require_access(self.org)
        self.subscription.delete()
        self.assertRedirects(self.client.get(reverse("legal:dashboard")), reverse("billing:subscription"))

    def test_export_preserves_historical_finance_after_downgrade_or_expiration(self):
        self.set_subscription(plan="max")
        record_payment(entry=self.entry, actor=self.owner, amount="40.00")
        for values in [{"plan": "start"}, {"plan": "max", "status": "suspended"},
                       {"status": "active", "expires_at": timezone.now() - timedelta(seconds=1)}]:
            self.set_subscription(**values)
            records, manifest = self.export_records()
            self.assertTrue(manifest["finance_included"])
            self.assertEqual(len(records["financeentry"]), 1)
            self.assertEqual(len(records["payment"]), 1)
            self.assertEqual(records["payment"][0]["amount"], "40.00")
            response = self.client.get(reverse("billing:subscription"))
            self.assertContains(response, reverse("legal:export"))

    def test_export_still_excludes_finance_for_viewer(self):
        self.set_subscription(plan="max", status="suspended")
        self.membership.role = "viewer"
        self.membership.save()
        records, manifest = self.export_records()
        self.assertFalse(manifest["finance_included"])
        self.assertNotIn("financeentry", records)
        self.assertNotIn("payment", records)

    def test_matter_create_reopen_and_edit_respect_active_only_capacity(self):
        with patch.dict(PLANS["start"], {"matters": 1}):
            response = self.client.post(reverse("legal:create", args=["matters"]), self.matter_data())
            self.assertContains(response, "Limite do plano Start")
            self.assertEqual(Matter.objects.count(), 1)
            response = self.client.post(reverse("legal:create", args=["matters"]), self.matter_data("Pasta encerrada", "closed"))
            self.assertEqual(response.status_code, 302)
            closed = Matter.objects.get(title="Pasta encerrada")
            response = self.client.post(reverse("legal:edit", args=["matters", closed.pk]), self.matter_data("Pasta encerrada", "active"))
            self.assertContains(response, "Limite do plano Start")
            closed.refresh_from_db()
            self.assertEqual(closed.status, "closed")
            response = self.client.post(reverse("legal:edit", args=["matters", self.matter.pk]), self.matter_data("Pasta renomeada"))
            self.assertEqual(response.status_code, 302)
            self.matter.refresh_from_db()
            self.assertEqual(self.matter.title, "Pasta renomeada")
            self.matter.status = "closed"
            self.matter.save()
            response = self.client.post(reverse("legal:edit", args=["matters", closed.pk]), self.matter_data("Pasta reaberta", "active"))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(usage(self.org)["matters"], 1)

    def test_document_version_service_enforces_total_versions_and_keeps_bytes(self):
        document = Document.objects.create(organization=self.org, matter=self.matter, title="Contrato", created_by=self.owner)
        with tempfile.TemporaryDirectory() as folder, override_settings(PRIVATE_MEDIA_ROOT=folder), patch.dict(PLANS["start"], {"versions": 2}):
            for content in [b"versao um", b"versao dois"]:
                add_document_version(document=document, actor=self.owner, file=SimpleUploadedFile("contrato.txt", content))
            before = {p.relative_to(folder): p.read_bytes() for p in Path(folder).rglob("*") if p.is_file()}
            with self.assertRaisesMessage(ValidationError, "versões de documentos"):
                add_document_version(document=document, actor=self.owner, file=SimpleUploadedFile("contrato.txt", b"bloqueada"))
            self.assertEqual(document.versions.count(), 2)
            after = {p.relative_to(folder): p.read_bytes() for p in Path(folder).rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.set_subscription(plan="max")
            add_document_version(document=document, actor=self.owner, file=SimpleUploadedFile("contrato.txt", b"terceira apos upgrade"))
            self.assertEqual(document.versions.count(), 3)

    def test_full_seat_capacity_prevents_acceptance_and_user_creation(self):
        for index in range(PLANS["start"]["members"] - 1):
            user = User.objects.create_user(f"member{index}@billing.test")
            Membership.objects.create(organization=self.org, user=user, role="viewer")
        invitation = self.invitation("new-seat@billing.test")
        self.client.logout()
        response = self.client.post(reverse("core:invitation", args=["billing-invitation"]), {
            "first_name": "Convidado", "password1": "TestOnlyPass!2026", "password2": "TestOnlyPass!2026",
        })
        self.assertEqual(response.status_code, 409)
        self.assertFalse(User.objects.filter(email=invitation.email).exists())
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)
        self.assertEqual(usage(self.org)["members"], PLANS["start"]["members"])

    def test_existing_active_member_acceptance_does_not_consume_a_seat(self):
        member = User.objects.create_user("existing-seat@billing.test")
        Membership.objects.create(organization=self.org, user=member, role="viewer")
        invitation = self.invitation(member.email)
        self.client.force_login(member)
        with patch.dict(PLANS["start"], {"members": 2}):
            response = self.client.post(reverse("core:invitation", args=["billing-invitation"]), {"accept": "1"})
        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(usage(self.org)["members"], 2)

    def test_capacity_checks_lock_office_inside_transaction(self):
        manager = Organization.objects
        with patch.object(manager, "select_for_update", wraps=manager.select_for_update) as lock:
            with transaction.atomic():
                check_capacity(self.org, "members")
                self.assertTrue(connection.in_atomic_block)
            lock.assert_called_once()

    def test_downgrade_validates_current_usage_and_admin_form(self):
        self.set_subscription(plan="max")
        Matter.objects.bulk_create([Matter(organization=self.org, owner=self.owner, title=f"Pasta {index}") for index in range(PLANS["start"]["matters"])])
        with self.assertRaisesMessage(ValidationError, "excede os limites"):
            validate_plan_change(self.org, "start")
        form = SubscriptionForm(data={"organization": self.org.pk, "plan": "start", "status": "active"}, instance=self.subscription)
        self.assertFalse(form.is_valid())
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, "max")
        Matter.objects.filter(organization=self.org).exclude(pk=self.matter.pk).update(status="closed")
        validate_plan_change(self.org, "start")

    def test_plan_request_never_activates_or_changes_existing_plan(self):
        self.set_subscription(status="pending")
        response = self.client.post(reverse("billing:subscription"), {"plan": "max"})
        self.assertRedirects(response, reverse("billing:subscription"))
        self.subscription.refresh_from_db()
        self.assertEqual((self.subscription.plan, self.subscription.status, self.subscription.requested_plan), ("start", "pending", "max"))
        event = self.subscription.events.get()
        self.assertEqual(event.actor, self.owner)
        self.assertIn("Não representa pagamento", event.description)
        self.membership.role = "manager"
        self.membership.save()
        self.assertEqual(self.client.post(reverse("billing:subscription"), {"plan": "start"}).status_code, 403)


@override_settings(**BILLING_TEST_SETTINGS)
@skipUnlessDBFeature("has_select_for_update")
class ConcurrentSeatAcceptanceTests(TransactionTestCase):
    """Runs on PostgreSQL; SQLite cannot verify SELECT FOR UPDATE serialization."""

    def test_two_invites_compete_for_last_available_seat(self):
        org = Organization.objects.create(name="Concorrência", slug="concorrencia", business_type="office")
        owner = User.objects.create_user("concurrent-owner@billing.test")
        occupants = [(owner, "owner")] + [(User.objects.create_user(f"concurrent-member-{index}@billing.test"), "viewer") for index in range(PLANS["start"]["members"] - 2)]
        for user, role in occupants:
            Membership.objects.create(organization=org, user=user, role=role)
        OrganizationSubscription.objects.create(organization=org, plan="start", status="active")
        contenders = []
        for index in range(2):
            user = User.objects.create_user(f"contender{index}@billing.test")
            token = f"concurrent-token-{index}"
            invitation = WorkspaceInvitation.objects.create(
                organization=org, email=user.email, role="viewer", invited_by=owner,
                token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=timezone.now() + timedelta(days=1),
            )
            contenders.append((user.pk, token, invitation.pk))
        barrier = threading.Barrier(2)

        def accept(contender):
            close_old_connections()
            try:
                user_id, token, _ = contender
                client = HttpClient()
                client.force_login(User.objects.get(pk=user_id))
                barrier.wait(timeout=10)
                response = client.post(reverse("core:invitation", args=[token]), {"accept": "1"})
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(accept, contenders))
        self.assertEqual(sorted(results), [302, 409])
        self.assertEqual(Membership.objects.filter(organization=org, is_active=True).count(), PLANS["start"]["members"])
        self.assertEqual(WorkspaceInvitation.objects.filter(organization=org, accepted_at__isnull=False).count(), 1)
