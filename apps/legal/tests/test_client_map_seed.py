from collections import Counter
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.management.commands.seed_client_map_demo import ACTION, SAMPLES
from apps.legal.models import AuditEvent, Contact, FinanceEntry, Matter, Payment
from apps.portal.models import ClientAccess, Publication


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
class ClientMapDemoSeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Demonstração local", slug="jumbi-demonstracao-local", business_type="office")
        cls.actor = get_user_model().objects.create_user(email="demo@jumbi.local")
        cls.membership = Membership.objects.create(organization=cls.org, user=cls.actor, role="manager")
        cls.subscription = OrganizationSubscription.objects.create(organization=cls.org, status="demo", plan="max")
        cls.existing = Contact.objects.create(organization=cls.org, name="Cadastro anterior", state="", country="", city="", notes="Preservar sem completar localização.")

    def command(self, *, apply=False, **kwargs):
        options = dict(organization=self.org.slug, email=self.actor.email, apply=apply, stdout=StringIO())
        options.update(kwargs)
        call_command("seed_client_map_demo", **options)
        return options["stdout"].getvalue()

    def counts(self):
        return {model._meta.model_name: model.objects.count() for model in [Contact, AuditEvent, Matter, ClientAccess, Publication, FinanceEntry, Payment]}

    def test_dry_run_is_readonly_and_reports_only_expected_distribution(self):
        before = self.counts()
        output = self.command()
        self.assertIn("PRÉVIA: 7", output)
        self.assertIn("CE: 2", output)
        self.assertEqual(self.counts(), before)

    def test_apply_adds_only_fictional_locations_and_preserves_existing_contacts(self):
        before = Contact.objects.filter(pk=self.existing.pk).values().get()
        self.command(apply=True)
        added = Contact.objects.exclude(pk=self.existing.pk)
        self.assertEqual(added.count(), 7)
        self.assertEqual(Counter(added.values_list("state", flat=True)), {"CE": 2, "SP": 1, "RJ": 1, "PE": 1, "DF": 1, "RS": 1})
        self.assertFalse(added.exclude(name__startswith="[DEMONSTRAÇÃO] Mapa · ").exists())
        self.assertFalse(added.exclude(country="Brasil").exists())
        self.assertFalse(added.exclude(notes__startswith="[DEMONSTRAÇÃO]").exists())
        for contact in added:
            for field in ("email", "phone", "document", "postal_code", "address", "address_complement", "district"):
                self.assertEqual(getattr(contact, field), "")
            self.assertIsNone(contact.birth_date)
        self.assertEqual(Contact.objects.filter(pk=self.existing.pk).values().get(), before)
        self.assertEqual(AuditEvent.objects.filter(action=ACTION).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="contact.demo_created").count(), 7)
        for model in [Matter, ClientAccess, Publication, FinanceEntry, Payment]:
            self.assertFalse(model.objects.exists())

    def test_reruns_do_not_overwrite_manually_edited_sample(self):
        self.command(apply=True)
        sample = Contact.objects.get(name=SAMPLES[0][0])
        sample.state = "BA"
        sample.city = "Salvador"
        sample.name = "[DEMONSTRAÇÃO] Renomeado pelo usuário"
        sample.save()
        before = self.counts()
        for apply in (False, True):
            self.assertIn("já cadastrados", self.command(apply=apply))
            self.assertEqual(self.counts(), before)
        sample.refresh_from_db()
        self.assertEqual((sample.state, sample.city, sample.name), ("BA", "Salvador", "[DEMONSTRAÇÃO] Renomeado pelo usuário"))

    def test_conflicting_reserved_name_rejects_every_write_even_with_changed_case(self):
        conflict = Contact.objects.create(organization=self.org, name=SAMPLES[-1][0].lower(), state="AM", city="Manaus")
        before = self.counts()
        for apply in (False, True):
            with self.subTest(apply=apply), self.assertRaises(CommandError):
                self.command(apply=apply)
        self.assertEqual(self.counts(), before)
        conflict.refresh_from_db()
        self.assertEqual((conflict.state, conflict.city), ("AM", "Manaus"))

    def test_late_error_rolls_back_all_contacts_and_audits(self):
        from apps.legal.services import audit as real_audit
        def fail_marker(**kwargs):
            if kwargs["action"] == ACTION:
                raise ValidationError("Falha final simulada")
            return real_audit(**kwargs)
        before = self.counts()
        with patch("apps.legal.management.commands.seed_client_map_demo.audit", side_effect=fail_marker):
            with self.assertRaises(CommandError):
                self.command(apply=True)
        self.assertEqual(self.counts(), before)

    def test_real_office_wrong_actor_and_mixed_demo_pairs_are_rejected(self):
        before = self.counts()
        for kwargs in [dict(organization="escritorio-real"), dict(email="admin@jumbi.nabio.pro"), dict(organization="jumbi-demonstracao", email="demo@jumbi.local")]:
            with self.subTest(kwargs=kwargs), self.assertRaises(CommandError):
                self.command(apply=True, **kwargs)
        self.assertEqual(self.counts(), before)

    def test_other_demo_pair_does_not_change_local_office(self):
        other = Organization.objects.create(name="Outra demonstração", slug="jumbi-demonstracao", business_type="office")
        actor = get_user_model().objects.create_user(email="demo@jumbi.nabio.pro")
        Membership.objects.create(organization=other, user=actor, role="owner")
        OrganizationSubscription.objects.create(organization=other, status="demo", plan="max")
        self.command(apply=True, organization=other.slug, email=actor.email)
        self.assertEqual(Contact.objects.filter(organization=other).count(), 7)
        self.assertEqual(Contact.objects.filter(organization=self.org).count(), 1)
        self.assertFalse(AuditEvent.objects.filter(organization=self.org).exists())

    def test_wrong_plan_real_active_subscription_or_expired_demo_rejected(self):
        before = self.counts()
        for change in [dict(plan="start"), dict(status="active"), dict(status="suspended"), dict(expires_at=timezone.now() - timedelta(days=1))]:
            previous = {field: getattr(self.subscription, field) for field in change}
            for field, value in change.items():
                setattr(self.subscription, field, value)
            self.subscription.save()
            with self.subTest(change=change), self.assertRaises(CommandError):
                self.command(apply=True)
            for field, value in previous.items():
                setattr(self.subscription, field, value)
            self.subscription.save()
        self.assertEqual(self.counts(), before)

    def test_inactive_office_or_user_revoked_membership_and_nonmanagers_rejected(self):
        before = self.counts()
        for change in [dict(role="operator"), dict(role="viewer"), dict(role="client"), dict(is_active=False)]:
            Membership.objects.filter(pk=self.membership.pk).update(**change)
            with self.subTest(change=change), self.assertRaises(CommandError):
                self.command(apply=True)
            Membership.objects.filter(pk=self.membership.pk).update(role="manager", is_active=True)
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
        with self.assertRaises(CommandError):
            self.command(apply=True)
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=True)
        Organization.objects.filter(pk=self.org.pk).update(status="suspended")
        with self.assertRaises(CommandError):
            self.command(apply=True)
        self.assertEqual(self.counts(), before)
