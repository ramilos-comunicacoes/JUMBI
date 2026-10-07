from urllib.parse import parse_qs, urlsplit
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.core.models import User, Organization, Membership
from .models import OrganizationSubscription


@override_settings(SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"], STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class WhatsAppContactTests(TestCase):
    def test_plan_cta_uses_exact_whatsapp_and_trusted_price(self):
        for plan, expected in [("start", "Start por R$ 89,90/mês"), ("max", "Max por R$ 199,90/mês")]:
            response = self.client.get(reverse("billing:contact", args=[plan]), {"price": "0", "phone": "123"})
            self.assertEqual(response.status_code, 302)
            url = urlsplit(response.url)
            self.assertEqual((url.scheme, url.netloc, url.path), ("https", "wa.me", "/5588992745456"))
            message = parse_qs(url.query)["text"][0]
            self.assertIn(expected, message)
            self.assertIn("contratação e a ativação", message)
            self.assertNotIn("Escritório:", message)
        self.assertEqual(self.client.get(reverse("billing:contact", args=["fake"])).status_code, 404)

    def test_pending_owner_has_personalized_contact_without_activation(self):
        owner = User.objects.create_user("owner@contact.test")
        org = Organization.objects.create(name="Escritório & Associados", slug="office", business_type="office")
        Membership.objects.create(organization=org, user=owner, role="owner")
        subscription = OrganizationSubscription.objects.create(organization=org, plan="start", requested_plan="max")
        self.client.force_login(owner)
        response = self.client.get(reverse("billing:subscription"))
        self.assertContains(response, reverse("billing:contact", args=["max"]))
        response = self.client.get(reverse("billing:contact", args=["max"]))
        message = parse_qs(urlsplit(response.url).query)["text"][0]
        self.assertIn("Escritório: Escritório & Associados.", message)
        self.assertNotIn(owner.email, message)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, "pending")
        self.assertEqual(subscription.events.count(), 0)
