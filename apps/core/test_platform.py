import io
import os
import tempfile
from unittest.mock import patch

from django.contrib import admin
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.legal.models import (
    Appointment, AuditEvent, Contact, CourtCase, Deadline, DocumentVersion,
    FinanceEntry, Matter, Opportunity, Payment, Task,
)
from apps.legal.services import visible_matters
from .models import Membership, Organization, User


TEST_SETTINGS = {
    "DEBUG": True, "SECURE_SSL_REDIRECT": False, "ALLOWED_HOSTS": ["testserver"],
    "JUMBI_ENFORCE_SUBSCRIPTIONS": False,
    "CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    "STORAGES": {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
}


@override_settings(**TEST_SETTINGS)
class PlatformTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("platform@example.test", "TestOnly!SecureAccount427")
        self.user = User.objects.create_user("member@example.test", "TestOnly!SecureAccount528")

    def test_platform_requires_authenticated_superuser(self):
        url = reverse("core:platform")
        self.assertRedirects(self.client.get(url), f"{reverse('core:login')}?next={url}")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(url)
        self.assertContains(response, "Controle da plataforma")
        self.assertContains(response, reverse("admin:index"))
        self.assertEqual(response.context["stats"]["users"], 1)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_superuser_without_membership_can_login_to_platform(self):
        response = self.client.post(reverse("core:login"), {"username": self.admin.email, "password": "TestOnly!SecureAccount427"})
        self.assertRedirects(response, reverse("core:platform"))

    def test_platform_paginates_organizations_and_members(self):
        for index in range(14):
            org = Organization.objects.create(name=f"Escritório {index}", slug=f"office-{index}", business_type="office")
            Membership.objects.create(user=self.user, organization=org)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("core:platform"))
        self.assertEqual(len(response.context["organizations_page"]), 12)
        self.assertEqual(response.context["stats"]["organizations"], 14)
        self.assertEqual(len(self.client.get(reverse("core:platform"), {"offices": 2}).context["organizations_page"]), 2)

    def test_superuser_does_not_gain_access_to_other_tenant_or_confidential_matter(self):
        org = Organization.objects.create(name="Privado", slug="private", business_type="office")
        Membership.objects.create(user=self.user, organization=org, role="owner")
        secret = Matter.objects.create(organization=org, owner=self.user, confidential=True, title="Pasta sigilosa")
        self.assertFalse(visible_matters(self.admin, org).exists())
        Membership.objects.create(user=self.admin, organization=org, role="owner")
        self.assertFalse(visible_matters(self.admin, org).filter(pk=secret.pk).exists())


@override_settings(**TEST_SETTINGS)
class ProvisionAccountsTests(TestCase):
    admin_email = "superuser@example.test"
    demo_email = "demo-account@example.test"
    passwords = {"JUMBI_ADMIN_PASSWORD": "TestOnly!PlatformSecret374", "JUMBI_DEMO_PASSWORD": "TestOnly!Demonstration584"}

    def setUp(self):
        cache.clear()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        media = override_settings(PRIVATE_MEDIA_ROOT=directory.name)
        media.enable()
        self.addCleanup(media.disable)

    def provision(self, **options):
        output = io.StringIO()
        with patch.dict(os.environ, self.passwords):
            call_command("provision_accounts", admin_email=self.admin_email, demo_email=self.demo_email, stdout=output, **options)
        return output.getvalue()

    def test_creates_separate_superuser_and_nonstaff_demo_with_private_sample_data_in_production(self):
        with override_settings(DEBUG=False, JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            output = self.provision(with_demo_data=True)
        admin_user = User.objects.get(email=self.admin_email)
        demo = User.objects.get(email=self.demo_email)
        self.assertTrue(admin_user.is_staff and admin_user.is_superuser)
        self.assertFalse(demo.is_staff or demo.is_superuser)
        self.assertTrue(admin_user.check_password(self.passwords["JUMBI_ADMIN_PASSWORD"]))
        self.assertTrue(demo.check_password(self.passwords["JUMBI_DEMO_PASSWORD"]))
        admin_membership = Membership.objects.get(user=admin_user)
        demo_membership = Membership.objects.get(user=demo)
        self.assertEqual(admin_membership.role, "owner")
        self.assertEqual(demo_membership.role, "manager")
        self.assertNotEqual(admin_membership.organization_id, demo_membership.organization_id)
        from apps.billing.models import OrganizationSubscription
        admin_subscription = OrganizationSubscription.objects.get(organization=admin_membership.organization)
        demo_subscription = OrganizationSubscription.objects.get(organization=demo_membership.organization)
        self.assertEqual((admin_subscription.plan, admin_subscription.status), ("max", "active"))
        self.assertEqual((demo_subscription.plan, demo_subscription.status), ("max", "demo"))
        self.assertFalse(Matter.objects.filter(organization=admin_membership.organization).exists())
        for model in [Contact, Matter, CourtCase, Task, Deadline, Appointment, DocumentVersion, FinanceEntry, Payment, Opportunity]:
            self.assertTrue(model.objects.filter(organization=demo_membership.organization).exists(), model.__name__)
        self.assertEqual(AuditEvent.objects.filter(action="platform.demo_seeded").count(), 1)
        for value in self.passwords.values():
            self.assertNotIn(value, output)
        self.client.force_login(demo)
        self.assertContains(self.client.get(reverse("legal:dashboard")), "Ambiente de demonstração")
        self.assertEqual(self.client.get(reverse("legal:list", args=["finance"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:platform")).status_code, 403)

    def test_repeat_preserves_passwords_and_does_not_duplicate_records(self):
        self.provision(with_demo_data=True)
        counts = (User.objects.count(), Organization.objects.count(), Matter.objects.count(), AuditEvent.objects.count())
        with patch.dict(os.environ, {"JUMBI_ADMIN_PASSWORD": "", "JUMBI_DEMO_PASSWORD": ""}):
            call_command("provision_accounts", admin_email=self.admin_email, demo_email=self.demo_email, with_demo_data=True, stdout=io.StringIO())
        self.assertEqual(counts, (User.objects.count(), Organization.objects.count(), Matter.objects.count(), AuditEvent.objects.count()))
        self.assertTrue(User.objects.get(email=self.admin_email).check_password(self.passwords["JUMBI_ADMIN_PASSWORD"]))
        self.assertTrue(User.objects.get(email=self.demo_email).check_password(self.passwords["JUMBI_DEMO_PASSWORD"]))

    def test_explicit_reset_is_required_to_replace_password(self):
        self.provision()
        new_passwords = {"JUMBI_ADMIN_PASSWORD": "TestOnly!ChangedSecret903", "JUMBI_DEMO_PASSWORD": "TestOnly!UpdatedSecret827"}
        with patch.dict(os.environ, new_passwords):
            call_command("provision_accounts", admin_email=self.admin_email, demo_email=self.demo_email, stdout=io.StringIO())
        self.assertTrue(User.objects.get(email=self.admin_email).check_password(self.passwords["JUMBI_ADMIN_PASSWORD"]))
        with patch.dict(os.environ, new_passwords):
            call_command("provision_accounts", admin_email=self.admin_email, demo_email=self.demo_email, reset_passwords=True, stdout=io.StringIO())
        self.assertTrue(User.objects.get(email=self.admin_email).check_password(new_passwords["JUMBI_ADMIN_PASSWORD"]))
        self.assertTrue(User.objects.get(email=self.demo_email).check_password(new_passwords["JUMBI_DEMO_PASSWORD"]))

    def test_missing_or_weak_password_rolls_back_both_accounts(self):
        for password in ["", "short", "123456789012345"]:
            with self.subTest(password_type="empty" if not password else "weak"):
                with patch.dict(os.environ, {**self.passwords, "JUMBI_DEMO_PASSWORD": password}):
                    with self.assertRaises(CommandError):
                        call_command("provision_accounts", admin_email=self.admin_email, demo_email=self.demo_email, stdout=io.StringIO())
                self.assertFalse(User.objects.exists())
                self.assertFalse(Organization.objects.exists())

    def test_never_promotes_existing_regular_user_or_reuses_staff_demo(self):
        existing = User.objects.create_user(self.admin_email, "TestOnly!ExistingSecret932")
        with self.assertRaises(CommandError):
            self.provision(reset_passwords=True)
        existing.refresh_from_db()
        self.assertFalse(existing.is_superuser)
        self.assertTrue(existing.check_password("TestOnly!ExistingSecret932"))
        self.assertFalse(User.objects.filter(email=self.demo_email).exists())

    def test_demo_cannot_share_an_existing_account_with_another_office(self):
        demo = User.objects.create_user(self.demo_email, "TestOnly!OtherOffice637")
        org = Organization.objects.create(name="Outro escritório", slug="other-office", business_type="office")
        Membership.objects.create(user=demo, organization=org)
        with self.assertRaises(CommandError):
            self.provision()
        self.assertFalse(User.objects.filter(email=self.admin_email).exists())
        self.assertEqual(Membership.objects.get(user=demo).organization_id, org.pk)

    def test_existing_demo_records_without_marker_are_never_overwritten(self):
        self.provision()
        demo_org = Organization.objects.get(slug="jumbi-demonstracao")
        Contact.objects.create(organization=demo_org, name="Registro preservado")
        with self.assertRaises(CommandError):
            self.provision(with_demo_data=True)
        self.assertEqual(Contact.objects.count(), 1)
        self.assertFalse(Matter.objects.exists())

    def test_legal_admin_is_readonly_and_private_file_renders_without_public_url(self):
        self.provision(with_demo_data=True)
        self.client.force_login(User.objects.get(email=self.admin_email))
        for model in (Matter, DocumentVersion, Payment, AuditEvent):
            obj = model.objects.first()
            url = reverse(f"admin:legal_{model._meta.model_name}_change", args=[obj.pk])
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.post(url, {"_save": "Salvar"}).status_code, 403)
            self.assertFalse(admin.site._registry[model].has_delete_permission(self.client.get(url).wsgi_request, obj))
