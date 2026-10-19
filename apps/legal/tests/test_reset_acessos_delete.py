from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization, OrganizationRole, WorkspaceInvitation
from apps.core.services import member_has_module
from apps.legal.models import (
    AdministrativeDemand, Appointment, Contact, CourtCase, Deadline,
    Document, DocumentVersion, FinanceEntry, Matter, Payment, Task,
)
from apps.legal.services import delete_contact_and_matters, reset_organization_operational_data

User = get_user_model()


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class ResetAndCascadeDeleteTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Advocacia Teste & Associados",
            slug="advocacia-teste",
            business_type="office",
            practice_areas=["previdenciario", "trabalhista"],
        )
        self.admin_user = User.objects.create_user(
            email="admin@teste.adv",
            password="admin_secret_pass_123",
            first_name="Dr.",
            last_name="Diretor",
        )
        self.admin_member = Membership.objects.create(
            organization=self.org,
            user=self.admin_user,
            role="owner",
        )
        self.operator_user = User.objects.create_user(
            email="operador@teste.adv",
            password="operador_pass_123",
            first_name="Operador",
            last_name="Silva",
        )
        self.operator_member = Membership.objects.create(
            organization=self.org,
            user=self.operator_user,
            role="operator",
            permissions=["contacts", "tasks"],  # Custom: only contacts and tasks
        )

    def test_delete_contact_cascades_matters_and_all_associated_records(self):
        self.client.login(username="admin@teste.adv", password="admin_secret_pass_123")
        contact = Contact.objects.create(
            organization=self.org,
            name="Joao da Silva",
            document="11122233344",
        )
        matter = Matter.objects.create(
            organization=self.org,
            client=contact,
            title="Pasta Aposentadoria · Joao da Silva",
            owner=self.admin_user,
            area="Previdenciário",
        )
        task = Task.objects.create(
            organization=self.org,
            matter=matter,
            owner=self.admin_user,
            title="Protocolar petição",
            due_date=timezone.localdate(),
        )
        deadline = Deadline.objects.create(
            organization=self.org,
            matter=matter,
            owner=self.admin_user,
            title="Prazo contestação",
            source="DJEN / Publicação oficial",
            due_date=timezone.localdate() + timedelta(days=10),
        )
        court_case = CourtCase.objects.create(
            organization=self.org,
            matter=matter,
            number="0001234-55.2026.8.00.0000",
        )
        demand = AdministrativeDemand.objects.create(
            organization=self.org,
            matter=matter,
            contact=contact,
            protocol_number="99887766",
            service_name="Aposentadoria por Idade",
            original_status="Em análise",
        )

        # GET confirmation page
        url = reverse("legal:contact_delete", args=[contact.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Joao da Silva")
        self.assertContains(res, "Pasta Aposentadoria · Joao da Silva")

        # POST deletion
        post_res = self.client.post(url, follow=True)
        self.assertEqual(post_res.status_code, 200)

        # Verify contact, matter, and all related items were deleted
        self.assertFalse(Contact.objects.filter(pk=contact.pk).exists())
        self.assertFalse(Matter.objects.filter(pk=matter.pk).exists())
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())
        self.assertFalse(Deadline.objects.filter(pk=deadline.pk).exists())
        self.assertFalse(CourtCase.objects.filter(pk=court_case.pk).exists())
        self.assertFalse(AdministrativeDemand.objects.filter(pk=demand.pk).exists())

    def test_reset_system_requires_admin_password_and_confirmation(self):
        # 1. Non-admin operator cannot access reset
        self.client.login(username="operador@teste.adv", password="operador_pass_123")
        url = reverse("core:reset_system")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 403)

        # 2. Admin can access GET
        self.client.login(username="admin@teste.adv", password="admin_secret_pass_123")
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Resetar dados operacionais do escritório")

        # 3. Create dummy data
        c = Contact.objects.create(organization=self.org, name="Cliente Teste")
        m = Matter.objects.create(organization=self.org, client=c, title="Pasta Teste", owner=self.admin_user)
        Task.objects.create(organization=self.org, matter=m, owner=self.admin_user, title="Tarefa Teste", due_date=timezone.localdate())

        # 4. Wrong password fails
        bad_post = self.client.post(url, {
            "password": "wrong_password_here",
            "confirmation_text": "RESETAR",
            "confirm_checkbox": "on",
        })
        self.assertEqual(bad_post.status_code, 200)
        self.assertContains(bad_post, "Senha incorreta")
        self.assertTrue(Matter.objects.filter(pk=m.pk).exists())

        # 5. Correct password and RESETAR cleans operational data
        good_post = self.client.post(url, {
            "password": "admin_secret_pass_123",
            "confirmation_text": "RESETAR",
            "confirm_checkbox": "on",
        }, follow=True)
        self.assertEqual(good_post.status_code, 200)

        # Check operational data was cleared
        self.assertEqual(Contact.objects.filter(organization=self.org).count(), 0)
        self.assertEqual(Matter.objects.filter(organization=self.org).count(), 0)
        self.assertEqual(Task.objects.filter(organization=self.org).count(), 0)

        # Check account and memberships are preserved
        self.assertTrue(Organization.objects.filter(pk=self.org.pk).exists())
        self.assertTrue(Membership.objects.filter(organization=self.org, user=self.admin_user).exists())
        self.assertTrue(Membership.objects.filter(organization=self.org, user=self.operator_user).exists())

    def test_custom_permissions_filter_modules_and_dashboard_is_general(self):
        # Operator has permissions=["contacts", "tasks"]
        self.assertTrue(member_has_module(self.operator_member, "contacts"))
        self.assertTrue(member_has_module(self.operator_member, "tasks"))
        self.assertFalse(member_has_module(self.operator_member, "finance"))
        self.assertFalse(member_has_module(self.operator_member, "djen"))
        self.assertFalse(member_has_module(self.operator_member, "demands"))

        self.client.login(username="operador@teste.adv", password="operador_pass_123")

        # Allowed module works
        res = self.client.get(reverse("legal:list", args=["contacts"]))
        self.assertEqual(res.status_code, 200)

        # Forbidden module returns 403
        res_forbidden = self.client.get(reverse("legal:list", args=["finance"]))
        self.assertEqual(res_forbidden.status_code, 403)

        # Dashboard is accessible and displays overall general stats
        res_dash = self.client.get(reverse("legal:dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertIn("stats", res_dash.context)

    def test_edit_member_allows_customizing_role_and_permissions(self):
        self.client.login(username="admin@teste.adv", password="admin_secret_pass_123")
        url = reverse("core:edit_member", args=[self.operator_member.pk])
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, 200)

        # Update operator to also have 'deadlines' and 'documents'
        post_res = self.client.post(url, {
            "role": "operator",
            "permissions": ["contacts", "tasks", "deadlines", "documents"],
            "is_active": "on",
        }, follow=True)
        self.assertEqual(post_res.status_code, 200)

        self.operator_member.refresh_from_db()
        self.assertIn("deadlines", self.operator_member.permissions)
        self.assertIn("documents", self.operator_member.permissions)
        self.assertTrue(member_has_module(self.operator_member, "deadlines"))
