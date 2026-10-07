import hashlib
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import Membership, Organization, User, WorkspaceInvitation


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False, DEBUG=True, SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"], STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class WorkspaceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.password = "SomenteTestes@Jumbi2026"
        self.owner = User.objects.create_user("owner@example.test", self.password, first_name="Pessoa")
        self.org = Organization.objects.create(name="Escritório A", slug="escritorio-a", business_type="office")
        self.member = Membership.objects.create(user=self.owner, organization=self.org, role="owner")

    def test_public_registration_creates_isolated_office(self):
        response = self.client.post(reverse("core:signup"), {"first_name": "Nova Pessoa", "email": "NOVA@example.test", "organization_name": "Novo escritório", "plan": "start", "password1": self.password, "password2": self.password})
        self.assertRedirects(response, reverse("billing:subscription"))
        user = User.objects.get(email="nova@example.test")
        membership = Membership.objects.get(user=user)
        self.assertEqual(membership.role, "owner")
        self.assertNotEqual(membership.organization_id, self.org.pk)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(membership.organization.subscription.status, "pending")

    def test_login_is_case_insensitive_and_rate_limited(self):
        response = self.client.post(reverse("core:login"), {"username": "OWNER@example.test", "password": self.password})
        self.assertRedirects(response, reverse("legal:dashboard"))
        self.client.logout()
        for _ in range(10):
            self.client.post(reverse("core:login"), {"username": self.owner.email, "password": "incorrect"})
        response = self.client.post(reverse("core:login"), {"username": self.owner.email, "password": self.password})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_revoked_membership_loses_existing_session_access(self):
        self.client.force_login(self.owner)
        self.member.is_active = False
        self.member.save()
        self.assertIn(self.client.get(reverse("legal:dashboard")).status_code, {302, 403})

    def test_suspended_office_cannot_be_accessed(self):
        self.client.force_login(self.owner)
        self.org.status = "suspended"
        self.org.save()
        self.assertIn(self.client.get(reverse("legal:dashboard")).status_code, {302, 403})

    def test_invitation_is_bound_to_email_and_revocable(self):
        token = "token-for-acceptance-test"
        invitation = WorkspaceInvitation.objects.create(organization=self.org, email="guest@example.test", role="viewer", token_hash=hashlib.sha256(token.encode()).hexdigest(), invited_by=self.owner, expires_at=timezone.now() + timedelta(days=1))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse("core:invitation", args=[token])).status_code, 403)
        self.client.post(reverse("core:revoke_invitation", args=[invitation.pk]))
        self.client.logout()
        self.assertEqual(self.client.get(reverse("core:invitation", args=[token])).status_code, 404)

    def test_new_guest_accepts_once_without_creating_another_office(self):
        token = "token-for-new-guest"
        WorkspaceInvitation.objects.create(organization=self.org, email="guest@example.test", role="viewer", token_hash=hashlib.sha256(token.encode()).hexdigest(), invited_by=self.owner, expires_at=timezone.now() + timedelta(days=1))
        response = self.client.post(reverse("core:invitation", args=[token]), {"first_name": "Convidado", "password1": self.password, "password2": self.password})
        self.assertRedirects(response, reverse("legal:dashboard"))
        self.assertEqual(Organization.objects.count(), 1)
        self.assertEqual(Membership.objects.get(user__email="guest@example.test").role, "viewer")
        self.assertEqual(self.client.post(reverse("core:invitation", args=[token])).status_code, 404)

    def test_team_does_not_allow_viewer_or_manager_escalation(self):
        self.member.role = "viewer"
        self.member.save()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("core:team")).status_code, 403)
        self.member.role = "manager"
        self.member.save()
        response = self.client.post(reverse("core:team"), {"email": "other@example.test", "role": "owner"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WorkspaceInvitation.objects.exists())

    def test_organization_switch_checks_membership(self):
        other = Organization.objects.create(name="Outro", slug="outro", business_type="office")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse("core:switch_organization"), {"organization_id": other.pk}).status_code, 404)

    def test_private_media_is_never_publicly_routed(self):
        self.assertEqual(self.client.get("/media/office/documents/test.pdf").status_code, 404)
        self.assertEqual(self.client.get("/private_media/documents/test.pdf").status_code, 404)

    def test_logout_requires_post(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("core:logout")).status_code, 405)
