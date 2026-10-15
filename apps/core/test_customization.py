import io
import tempfile
from copy import deepcopy
from PIL import Image, ImageDraw
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.billing.models import OrganizationSubscription
from apps.legal.models import AuditEvent, Contact
from apps.legal.calendar_services import birthday_link
from .models import Organization, Membership, User
from .preferences import DEFAULTS, NAV_CHOICES
from .customization_forms import WorkspaceCustomizationForm


class CustomizationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Escritório Alfa", slug="alfa", business_type="office")
        self.other = Organization.objects.create(name="Escritório Beta", slug="beta", business_type="office")
        self.user = User.objects.create_user(email="owner@example.test", password="SamplePassword123!")
        self.member = Membership.objects.create(organization=self.org, user=self.user, role="owner")
        OrganizationSubscription.objects.create(organization=self.org, plan="max", status="active")
        self.client.force_login(self.user)

    def data(self, **changes):
        data = deepcopy(DEFAULTS)
        data.update(name=self.org.name, system_title="Marca Alfa", brand_primary_color="#2563eb", brand_accent_color="#0f766e",
            brand_sidebar_color="#ffffff", glassmorphism_intensity="ultra", practice_areas=["civil", "trabalhista"], revision=self.org.updated_at.isoformat())
        data.update(changes)
        return data

    def test_preferences_saved_applied_and_isolated(self):
        response = self.client.post(reverse("core:customization"), self.data(density="compact", text_size="large", sidebar_mode="manual", hidden_nav=["crm"], dashboard_widgets=[], nav_order=["contacts", "tasks"]))
        self.assertEqual(response.status_code, 302)
        self.org.refresh_from_db(); self.other.refresh_from_db()
        self.assertEqual(self.org.workspace_preferences["density"], "compact")
        self.assertEqual(self.other.workspace_preferences, {})
        page = self.client.get(reverse("legal:dashboard"))
        self.assertContains(page, 'data-sidebar-mode="manual"')
        self.assertContains(page, '--office-primary:#2563eb')
        self.assertNotIn("crm", [item["key"] for item in page.context["nav"]])
        self.assertEqual(page.context["nav"][0]["key"], "contacts")
        self.assertNotContains(page, 'id="overview-calendar"')
        self.assertContains(page, "Próximos prazos")
        self.assertTrue(AuditEvent.objects.filter(organization=self.org, action="organization.customized").exists())
        self.assertContains(self.client.get(reverse("core:audit")), "Personalização atualizada")

    def test_invalid_options_or_injected_css_do_not_save(self):
        for change in [{"brand_primary_color": "red;display:none"}, {"theme": "bad"}, {"hidden_nav": ["security"]}, {"nav_order": ["contacts", "contacts"]}, {"birthday_message": "Olá {segredo}"}]:
            with self.subTest(change=change):
                response = self.client.post(reverse("core:customization"), self.data(**change))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.org.refresh_from_db()
                self.assertEqual(self.org.system_title, "JUMBI")

    def test_concurrent_edit_is_rejected(self):
        data = self.data()
        self.org.name = "Outra edição"; self.org.save()
        response = self.client.post(reverse("core:customization"), data)
        self.assertContains(response, "Outra pessoa atualizou")
        self.org.refresh_from_db(); self.assertEqual(self.org.name, "Outra edição")

    def test_operator_cannot_change_preferences(self):
        self.member.role = "operator"; self.member.save()
        self.assertEqual(self.client.post(reverse("core:customization"), self.data()).status_code, 403)

    def test_image_is_decoded_not_trusted_by_extension(self):
        for name, content, mime in [("logo.png", b"not an image", "image/png"), ("logo.svg", b'<svg onload="alert(1)"/>', "image/svg+xml")]:
            form = WorkspaceCustomizationForm(self.data(), {"brand_logo": SimpleUploadedFile(name, content, content_type=mime)}, instance=self.org)
            self.assertFalse(form.is_valid())
            self.assertIn("brand_logo", form.errors)

    def test_valid_image_normalized(self):
        out = io.BytesIO(); logo = Image.new("RGB", (40,40), "white")
        ImageDraw.Draw(logo).rectangle((10,10,30,30), fill="red"); logo.save(out, "JPEG")
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            form = WorkspaceCustomizationForm(self.data(), {"brand_logo": SimpleUploadedFile("logo.jpg", out.getvalue(), content_type="image/jpeg")}, instance=self.org)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["brand_logo"].content_type, "image/png")

    def test_birthday_message_uses_encoded_office_template(self):
        self.org.workspace_preferences = {"birthday_message": "Olá {cliente}, parabéns! — {escritorio}"}
        contact = Contact(name="Ana & Cia", organization=self.org, phone="88999999999")
        from urllib.parse import parse_qs, urlsplit
        text = parse_qs(urlsplit(birthday_link(contact, self.org)).query)["text"][0]
        self.assertIn("Ana & Cia", text); self.assertIn(self.org.name, text)

    def test_superuser_without_office_can_open_platform(self):
        user = User.objects.create_superuser(email="root@example.test", password="SamplePassword123!")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("core:platform")).status_code, 200)

    def test_calendar_default_and_compact_dashboard(self):
        self.org.workspace_preferences={"calendar_view":"week", "dashboard_view":"compact"}; self.org.save()
        response = self.client.get(reverse("legal:dashboard"))
        self.assertTrue(response.context["compact_mode"])
        self.assertNotContains(response, 'id="overview-calendar"')
        calendar = self.client.get(reverse("legal:calendar"))
        self.assertEqual(calendar.status_code, 200)
        self.assertEqual(calendar.context["calendar_filter_form"].cleaned_data["view"], "week")

    def test_dashboard_blocks_are_independent(self):
        blocks = {"calendar": 'id="overview-calendar"', "goals": 'aria-label="Metas do período"', "insights": 'overview-reporting', "activity": 'overview-records', "routines": 'Conferências pendentes'}
        for selected, marker in blocks.items():
            with self.subTest(widget=selected):
                self.org.workspace_preferences = {"dashboard_widgets": [selected]}
                self.org.save()
                response = self.client.get(reverse("legal:dashboard"))
                self.assertContains(response, marker)
                for other, other_marker in blocks.items():
                    if other != selected:
                        self.assertNotContains(response, other_marker)
                self.assertContains(response, "Próximos prazos")
