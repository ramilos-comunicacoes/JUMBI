from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization
from apps.legal.models import AdministrativeDemand, Contact, Deadline, Matter, Task

User = get_user_model()


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class PrevidenciarioHubTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Escritório Previdenciário Beta", slug="prev-beta", business_type="office")
        self.user = User.objects.create_user(
            email="prev_adv@test.com",
            password="testpassword123",
            first_name="Dra.",
            last_name="Previdenciarista",
        )
        self.membership = Membership.objects.create(
            organization=self.org,
            user=self.user,
            role="owner",
        )
        self.client.login(username="prev_adv@test.com", password="testpassword123")

        # Contact and Matter
        self.contact = Contact.objects.create(
            organization=self.org,
            name="João da Silva Segurado",
            document="12345678900",
        )
        self.matter = Matter.objects.create(
            organization=self.org,
            title="Aposentadoria Especial - João da Silva",
            client=self.contact,
            area="Previdenciário",
            status=Matter.Status.ACTIVE,
            owner=self.user,
        )

        # Administrative Demands
        self.demand_req = AdministrativeDemand.objects.create(
            organization=self.org,
            matter=self.matter,
            contact=self.contact,
            protocol_number="INSS-2024-9988",
            service_name="Aposentadoria por Idade Urbana",
            original_status="Exigência pendente",
            status=AdministrativeDemand.Status.REQUIREMENT,
            demands_summary="Apresentar certidão de casamento e cópia da CTPS nº 12345.",
            requirement_due_date=timezone.localdate() + timedelta(days=12),
        )

    def test_previdenciario_hub_renders_successfully(self):
        url = reverse("legal:previdenciario_hub")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Direito Previdenciário & INSS")
        self.assertContains(response, "INSS-2024-9988")
        self.assertContains(response, "Simulador EC 103/2019")
        self.assertContains(response, "Checklist de Documentos por Benefício")
        self.assertContains(response, "Mandado de Segurança por Excesso de Prazo do INSS")
        self.assertEqual(response.context["requirement_count"], 1)

    def test_demand_action_criar_prazo(self):
        url = reverse("legal:demand_action", kwargs={"pk": self.demand_req.pk, "action": "criar_prazo"})
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify Deadline was created with strict integrity
        deadline = Deadline.objects.filter(matter=self.matter).first()
        self.assertIsNotNone(deadline)
        self.assertEqual(deadline.status, Deadline.Status.PENDING)
        self.assertEqual(deadline.kind, Deadline.Kind.ADMINISTRATIVE)
        self.assertEqual(deadline.due_date, self.demand_req.requirement_due_date)

        # Verify linked Task was created with URGENT priority
        task = Task.objects.filter(matter=self.matter).first()
        self.assertIsNotNone(task)
        self.assertEqual(task.priority, Task.Priority.URGENT)
        self.assertEqual(task.deadline, deadline)

    def test_demand_action_cumprir(self):
        url = reverse("legal:demand_action", kwargs={"pk": self.demand_req.pk, "action": "cumprir"})
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 200)

        self.demand_req.refresh_from_db()
        self.assertEqual(self.demand_req.status, AdministrativeDemand.Status.PENDING)
        self.assertIn("Exigência cumprida", self.demand_req.next_action)

    def test_demand_action_judicializar(self):
        url = reverse("legal:demand_action", kwargs={"pk": self.demand_req.pk, "action": "judicializar"})
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 200)

        self.demand_req.refresh_from_db()
        self.assertEqual(self.demand_req.status, AdministrativeDemand.Status.REJECTED)
        self.assertIn("Encaminhado para judicialização", self.demand_req.next_action)

        # Verify petition task was created
        judicial_task = Task.objects.filter(matter=self.matter, title__icontains="Distribuir Ação").first()
        self.assertIsNotNone(judicial_task)
        self.assertEqual(judicial_task.priority, Task.Priority.HIGH)

    def test_demand_action_cross_tenant_forbidden(self):
        # Create second org and user
        other_org = Organization.objects.create(name="Outro Escritório", slug="outro-prev", business_type="office")
        other_user = User.objects.create_user(
            email="outro@test.com",
            password="testpassword123",
        )
        Membership.objects.create(
            organization=other_org,
            user=other_user,
            role="owner",
        )
        self.client.login(username="outro@test.com", password="testpassword123")

        # Attempt to modify demand belonging to first org
        url = reverse("legal:demand_action", kwargs={"pk": self.demand_req.pk, "action": "cumprir"})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
