import io
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.billing.models import OrganizationSubscription
from .admin import PlatformMembershipForm, PlatformUserChangeForm
from .management.commands.isolate_legacy_accounts import RESERVED_EMAILS
from .models import AuditLog, Membership, Organization, OrganizationRole, User


@override_settings(DEBUG=True, SECURE_SSL_REDIRECT=False, JUMBI_ENFORCE_SUBSCRIPTIONS=False, ALLOWED_HOSTS=["testserver"], STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class LegacyIsolationTests(TestCase):
    def setUp(self):
        self.office = Organization.objects.create(name="Escritório JUMBI", slug="jumbi-test", business_type="office")
        self.engineering = Organization.objects.create(name="Empresa de outra aplicação", slug="engineering-test", business_type="engineering")
        self.suspended = Organization.objects.create(name="Escritório suspenso", slug="suspended-test", business_type="office", status="suspended")
        self.office_user = self.user("office", self.office, privileged=True)
        self.external_user = self.user("external", self.engineering, privileged=True)
        self.mixed_user = self.user("mixed", self.office, privileged=True)
        Membership.objects.create(user=self.mixed_user, organization=self.engineering)
        self.inactive_user = self.user("inactive", self.office, active=False, privileged=True)
        self.suspended_user = self.user("suspended", self.suspended)
        self.revoked_user = self.user("revoked", self.office)
        self.revoked_user.memberships.update(is_active=False)
        self.orphan_user = self.user("orphan")
        self.reserved_admin = User.objects.create_superuser(RESERVED_EMAILS[0].upper(), "TestOnly!PreservedAccount943")
        self.reserved_demo = User.objects.create_user(RESERVED_EMAILS[1], "TestOnly!PreservedAccount943")
        self.permission = Permission.objects.get(content_type__app_label="core", codename="change_user")
        self.group = Group.objects.create(name="Grupo herdado")
        for user in (self.office_user, self.external_user, self.mixed_user, self.reserved_admin):
            user.groups.add(self.group)
            user.user_permissions.add(self.permission)

    def user(self, label, organization=None, *, active=True, privileged=False):
        user = User.objects.create_user(f"{label}@example.test", "TestOnly!LegacyAccount746", is_active=active, is_staff=privileged, is_superuser=privileged)
        if organization:
            Membership.objects.create(user=user, organization=organization, role="owner")
        return user

    def run_command(self, **options):
        output = io.StringIO()
        call_command("isolate_legacy_accounts", expected_db=str(connection.settings_dict["NAME"]), stdout=output, **options)
        return output.getvalue()

    def test_dry_run_by_default_does_not_alter_any_account_or_membership(self):
        users = list(User.objects.values())
        memberships = list(Membership.objects.values())
        output = self.run_command()
        self.assertIn("SIMULAÇÃO SEM ALTERAÇÕES", output)
        self.assertIn("Contas desativadas: 4", output)
        self.assertEqual(list(User.objects.values()), users)
        self.assertEqual(list(Membership.objects.values()), memberships)
        self.assertTrue(self.external_user.groups.exists())
        self.assertTrue(self.external_user.user_permissions.exists())

    def test_apply_quarantines_external_access_preserves_passwords_and_never_reactivates(self):
        passwords = dict(User.objects.values_list("pk", "password"))
        membership_count = Membership.objects.count()
        self.run_command(apply=True)
        for user in (self.external_user, self.orphan_user, self.suspended_user, self.revoked_user, self.inactive_user):
            user.refresh_from_db()
            self.assertFalse(user.is_active)
        for user in (self.office_user, self.mixed_user):
            user.refresh_from_db()
            self.assertTrue(user.is_active)
        for user in User.objects.exclude(pk__in=[self.reserved_admin.pk, self.reserved_demo.pk]):
            self.assertFalse(user.is_staff or user.is_superuser)
            self.assertFalse(user.groups.exists())
            self.assertFalse(user.user_permissions.exists())
        self.reserved_admin.refresh_from_db()
        self.reserved_demo.refresh_from_db()
        self.assertTrue(self.reserved_admin.is_active and self.reserved_admin.is_superuser and self.reserved_admin.is_staff)
        self.assertTrue(self.reserved_admin.groups.exists())
        self.assertTrue(self.reserved_admin.user_permissions.exists())
        self.assertTrue(self.reserved_demo.is_active)
        self.assertEqual(passwords, dict(User.objects.values_list("pk", "password")))
        self.assertEqual(Membership.objects.count(), membership_count)
        self.assertIn("Contas desativadas: 0", self.run_command(apply=True))

    def test_database_mismatch_and_original_database_are_refused_before_mutation(self):
        before = list(User.objects.values())
        with self.assertRaises(CommandError):
            call_command("isolate_legacy_accounts", expected_db="not-the-connected-database", apply=True, stdout=io.StringIO())
        with patch("apps.core.management.commands.isolate_legacy_accounts.connected_database_name", return_value="djumbi"):
            with self.assertRaises(CommandError):
                call_command("isolate_legacy_accounts", expected_db="djumbi", apply=True, stdout=io.StringIO())
        self.assertEqual(before, list(User.objects.values()))

    def test_legacy_apps_keep_models_but_have_no_admin_routes(self):
        labels = {model._meta.app_label for model in admin.site._registry}
        self.assertTrue(labels.issubset({"auth", "core", "legal", "billing"}))
        from apps.engineering.models import Project
        self.assertFalse(admin.site.is_registered(Project))
        self.client.force_login(self.reserved_admin)
        self.assertEqual(self.client.get("/admin/engineering/project/").status_code, 404)

    def test_platform_and_core_admin_hide_nonlegal_organizations_and_users(self):
        self.run_command(apply=True)
        self.client.force_login(self.reserved_admin)
        response = self.client.get(reverse("core:platform"))
        self.assertContains(response, self.office.name)
        self.assertNotContains(response, self.engineering.name)
        self.assertNotContains(response, self.external_user.email)
        self.assertEqual(response.context["stats"]["organizations"], 2)
        for model, forbidden in ((Organization, self.engineering.name), (User, self.external_user.email), (Membership, self.engineering.name)):
            response = self.client.get(reverse(f"admin:core_{model._meta.model_name}_changelist"))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, forbidden)
        for model, obj in ((Organization, self.engineering), (User, self.external_user)):
            response = self.client.get(reverse(f"admin:core_{model._meta.model_name}_change", args=[obj.pk]))
            self.assertEqual(response.status_code, 302)

    def test_admin_relationship_choices_and_permission_groups_exclude_legacy_apps(self):
        self.run_command(apply=True)
        request = RequestFactory().get("/admin/")
        request.user = self.reserved_admin
        membership_admin = admin.site._registry[Membership]
        form = membership_admin.get_form(request)()
        self.assertNotIn(self.engineering, form.fields["organization"].queryset)
        self.assertNotIn(self.external_user, form.fields["user"].queryset)
        legacy_permission = Permission.objects.filter(content_type__app_label="engineering").first()
        legacy_group = Group.objects.create(name="Acesso Engenharia")
        legacy_group.permissions.add(legacy_permission)
        user_form = admin.site._registry[User].get_form(request, self.reserved_admin)()
        self.assertNotIn(legacy_permission, user_form.fields["user_permissions"].queryset)
        self.assertNotIn(legacy_group, user_form.fields["groups"].queryset)
        self.assertNotIn(legacy_group, admin.site._registry[Group].get_queryset(request))


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
class AdminCapacityTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Start lotado", slug="start-full", business_type="office")
        OrganizationSubscription.objects.create(organization=self.organization, plan="start", status="active")
        for index in range(3):
            user = User.objects.create_user(f"active-{index}@example.test", "TestOnly!Capacity963")
            Membership.objects.create(organization=self.organization, user=user, role="operator")
        self.waiting = User.objects.create_user("waiting@example.test", "TestOnly!Capacity963")

    def test_admin_cannot_create_or_reactivate_membership_beyond_plan_capacity(self):
        payload = {"organization": self.organization.pk, "user": self.waiting.pk, "role": "operator", "is_active": True}
        form = PlatformMembershipForm(data=payload)
        self.assertFalse(form.is_valid())
        self.assertIn("Limite do plano", str(form.errors))
        member = Membership.objects.create(organization=self.organization, user=self.waiting, is_active=False)
        form = PlatformMembershipForm(data=payload, instance=member)
        self.assertFalse(form.is_valid())
        member.refresh_from_db()
        self.assertFalse(member.is_active)

    def test_admin_can_reactivate_membership_after_capacity_is_available(self):
        Membership.objects.filter(organization=self.organization).first().delete()
        member = Membership.objects.create(organization=self.organization, user=self.waiting, is_active=False)
        form = PlatformMembershipForm(data={"organization": self.organization.pk, "user": self.waiting.pk, "role": "operator", "is_active": True}, instance=member)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.save().is_active)

    def test_admin_cannot_transfer_existing_membership_to_another_office(self):
        other = Organization.objects.create(name="Outro", slug="other-capacity", business_type="office")
        member = Membership.objects.first()
        form = PlatformMembershipForm(data={"organization": other.pk, "user": member.user_id, "role": "operator", "is_active": True}, instance=member)
        self.assertFalse(form.is_valid())
        self.assertIn("Preserve o vínculo", str(form.errors))

    def test_admin_user_reactivation_checks_quota_of_all_existing_office_memberships(self):
        self.waiting.is_active = False
        self.waiting.save()
        Membership.objects.create(organization=self.organization, user=self.waiting, is_active=True)
        form = PlatformUserChangeForm(data={"email": self.waiting.email, "is_active": True, "password": self.waiting.password, "date_joined": self.waiting.date_joined}, instance=self.waiting)
        self.assertFalse(form.is_valid())
        self.assertIn("Limite do plano", str(form.errors))
        self.waiting.refresh_from_db()
        self.assertFalse(self.waiting.is_active)
