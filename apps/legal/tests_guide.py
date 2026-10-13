"""The guide must link only to features the current role and plan can open."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.models import Contact, Matter


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
class WorkspaceGuideTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Escritório guia", slug="guide-alpha", business_type="office")
        cls.other = Organization.objects.create(name="Outro escritório guia", slug="guide-beta", business_type="office")
        cls.subscription = OrganizationSubscription.objects.create(organization=cls.org, plan="max", status="active")
        OrganizationSubscription.objects.create(organization=cls.other, plan="start", status="active")
        for name, role in [("owner", "owner"), ("operator", "operator"), ("viewer", "viewer"), ("client_user", "client")]:
            user = get_user_model().objects.create_user(email=f"{name}-guide@example.test", password="guide-tests-only")
            setattr(cls, name, user)
            setattr(cls, name + "_membership", Membership.objects.create(organization=cls.org, user=user, role=role))
        Membership.objects.create(organization=cls.other, user=cls.owner, role="viewer")
        Contact.objects.create(organization=cls.org, name="DADO PRIVADO QUE NÃO PERTENCE AO GUIA")
        Matter.objects.create(organization=cls.org, title="PASTA SIGILOSA AUSENTE DO GUIA", owner=cls.owner, confidential=True)

    def guide(self, user, plan="max"):
        self.subscription.plan = plan
        self.subscription.save()
        self.client.force_login(user)
        session = self.client.session
        session["active_organization_id"] = self.org.pk
        session.save()
        return self.client.get(reverse("legal:guide"))

    def assert_opens(self, response, names):
        for name in names:
            with self.subTest(route=name):
                url = reverse(name)
                self.assertContains(response, f'href="{url}"')
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_anonymous_must_authenticate_before_opening_internal_guide(self):
        response = self.client.get(reverse("legal:guide"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("core:login")))

    def test_start_viewer_has_working_basic_links_without_advanced_or_write_links(self):
        response = self.guide(self.viewer, plan="start")
        self.assertEqual(response.status_code, 200)
        self.assert_opens(response, ["legal:calendar", "legal:kanban", "legal:client_map", "performance:list", "routines:list", "discovery:search", "security:account"])
        for route in ["contracts:library", "portal:manage", "fees:overview", "inventory:overview", "inventory:assets"]:
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertNotContains(response, f'href="{reverse("legal:list", args=["finance"])}"')
        self.assertEqual(self.client.get(reverse("legal:list", args=["crm"])).status_code, 200)
        self.assertNotContains(response, f'href="{reverse("legal:create", args=["contacts"])}"')

    def test_start_owner_guide_does_not_advertise_advanced_actions(self):
        response = self.guide(self.owner, plan="start")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["advanced_access"])
        for route in ["contracts:library", "fees:overview", "inventory:overview"]:
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertContains(response, f'href="{reverse("legal:list", args=["crm"])}"')

    def test_max_owner_links_open_real_management_modules(self):
        response = self.guide(self.owner)
        self.assertEqual(response.status_code, 200)
        self.assert_opens(response, ["contracts:library", "portal:manage", "fees:overview", "inventory:overview", "inventory:assets"])
        self.assertEqual(self.client.get(reverse("legal:list", args=["finance"])).status_code, 200)
        self.assertContains(response, "A geração não é assinatura eletrônica.")
        self.assertContains(response, "não envia mensagens automaticamente")

    def test_max_viewer_sees_contract_reading_but_not_financial_or_portal_management(self):
        response = self.guide(self.viewer)
        self.assertEqual(response.status_code, 200)
        self.assert_opens(response, ["contracts:library"])
        for route in ["portal:manage", "fees:overview", "inventory:overview", "inventory:assets"]:
            self.assertNotContains(response, f'href="{reverse(route)}"')
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_operator_gets_portal_but_not_financial_guidance_actions(self):
        response = self.guide(self.operator)
        self.assertEqual(response.status_code, 200)
        self.assert_opens(response, ["portal:manage", "contracts:library"])
        self.assertNotContains(response, f'href="{reverse("fees:overview")}"')
        self.assertNotContains(response, f'href="{reverse("inventory:overview")}"')

    def test_client_and_revoked_members_cannot_open_guide(self):
        self.assertEqual(self.guide(self.client_user).status_code, 403)
        self.viewer_membership.is_active = False
        self.viewer_membership.save()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("legal:guide")).status_code, 403)

    def test_selected_office_controls_plan_and_guide_does_not_expose_case_data(self):
        self.guide(self.owner)
        session = self.client.session
        session["active_organization_id"] = self.other.pk
        session.save()
        response = self.client.get(reverse("legal:guide"), {"organization": self.org.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["organization"].pk, self.other.pk)
        self.assertFalse(response.context["advanced_access"])
        self.assertFalse(response.context["can_manage"])
        self.assertNotContains(response, "DADO PRIVADO QUE NÃO PERTENCE AO GUIA")
        self.assertNotContains(response, "PASTA SIGILOSA AUSENTE DO GUIA")
        self.assertNotContains(response, f'href="{reverse("fees:overview")}"')

    def test_guide_is_get_only_private_and_suspended_plan_stays_blocked(self):
        response = self.guide(self.owner)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.post(reverse("legal:guide"), {}).status_code, 405)
        self.subscription.status = "suspended"
        self.subscription.save()
        blocked = self.client.get(reverse("legal:guide"))
        self.assertRedirects(blocked, reverse("billing:subscription"), fetch_redirect_response=False)
