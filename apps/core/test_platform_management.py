from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.billing.models import OrganizationSubscription, SubscriptionEvent
from .models import AuditLog, Membership, Organization, User
from .niches import validate_practice_areas
from .platform_services import create_office, configure_office
from .test_platform import TEST_SETTINGS


@override_settings(**TEST_SETTINGS)
class PlatformManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("super@platform.test", "SecureOnly!Pass4847")
        self.user = User.objects.create_user("member@platform.test", "SecureOnly!Pass4848")
        self.data = {
            "name": "Escritório misto", "owner_name": "Direção", "owner_email": "owner@new.test",
            "password": "OnlyForTesting!Strong397", "password_confirmation": "OnlyForTesting!Strong397",
            "practice_areas": ["civil", "familia", "trabalhista", "previdenciario"],
            "plan": "start", "subscription_status": "active", "contact_email": "office@new.test", "contact_phone": "",
        }

    def test_superuser_creates_mixed_office_account_plan_atomically_without_promoting_owner(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("platform:office_create")), "Áreas de atuação")
        response = self.client.post(reverse("platform:office_create"), self.data)
        self.assertRedirects(response, reverse("core:platform"))
        office = Organization.objects.get(name=self.data["name"])
        owner = User.objects.get(email=self.data["owner_email"])
        self.assertEqual(office.practice_areas, self.data["practice_areas"])
        self.assertEqual(len(office.practice_area_labels), 4)
        self.assertEqual(office.business_type, "office")
        self.assertFalse(owner.is_staff or owner.is_superuser)
        self.assertTrue(owner.check_password(self.data["password"]))
        self.assertEqual(Membership.objects.get(user=owner).role, "owner")
        self.assertEqual((office.subscription.plan, office.subscription.status), ("start", "active"))
        self.assertEqual(SubscriptionEvent.objects.filter(subscription=office.subscription).count(), 1)
        self.assertNotIn(self.data["password"], str(list(AuditLog.objects.values())))
        self.assertNotIn(self.data["password"], str(list(SubscriptionEvent.objects.values())))
        self.assertFalse(Membership.objects.filter(user=self.admin).exists())

    def test_permissions_and_invalid_data_cannot_create_or_configure_accounts(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("platform:office_create"), self.data).status_code, 403)
        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self.client.get(reverse("platform:office_create")).status_code, 403)
        with self.assertRaises(PermissionDenied):
            create_office(actor=self.user, data=self.data)
        self.client.force_login(self.admin)
        for changes in [{"password": "short", "password_confirmation": "short"}, {"password_confirmation": "different"}, {"practice_areas": ["bogus"]}, {"plan": "free"}]:
            with self.subTest(changes=changes):
                response = self.client.post(reverse("platform:office_create"), {**self.data, **changes})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertFalse(Organization.objects.exists())
        with patch("apps.core.platform_services.SubscriptionEvent.objects.create", side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                create_office(actor=self.admin, data=self.data)
        self.assertFalse(Organization.objects.exists())
        self.assertFalse(User.objects.filter(email=self.data["owner_email"]).exists())

    def test_configuration_records_history_and_rejects_non_office(self):
        office = create_office(actor=self.admin, data=self.data)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("platform:office_configure", args=[office.pk]), self.data).status_code, 403)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(reverse("platform:office_configure", args=[office.pk]), {**self.data, "practice_areas": ["civil", "criminal", "tributario"]}), reverse("core:platform"))
        office.refresh_from_db()
        self.assertEqual(office.practice_areas, ["civil", "criminal", "tributario"])
        event = AuditLog.objects.get(action="platform.office_configured")
        self.assertEqual(event.metadata["previous_practice_areas"], self.data["practice_areas"])
        other = Organization.objects.create(name="Agro", slug="agro", business_type="agro")
        self.assertEqual(self.client.get(reverse("platform:office_configure", args=[other.pk])).status_code, 404)

    def test_niche_validator_and_admin_restrict_non_superuser(self):
        for value in ["civil", ["nope"], ["civil", "civil"], [8]]:
            with self.assertRaises(ValidationError):
                validate_practice_areas(value)
        from django.contrib import admin
        from django.test import RequestFactory
        instance = admin.site._registry[Organization]
        request = RequestFactory().get("/admin/")
        request.user = self.user
        self.assertIn("practice_areas", instance.get_readonly_fields(request))
        request.user = self.admin
        self.assertNotIn("practice_areas", instance.get_readonly_fields(request))
