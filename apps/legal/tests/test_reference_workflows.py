from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization
from apps.legal.models import Contact, Matter, Opportunity, Task


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class ReferenceWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Referências", slug="reference-flow", business_type="office", practice_areas=["civil"])
        cls.other = Organization.objects.create(name="Outro", slug="reference-other", business_type="office")
        for name, role, org in [("owner", "owner", cls.org), ("viewer", "viewer", cls.org), ("portal", "client", cls.org), ("outsider", "owner", cls.other)]:
            user = get_user_model().objects.create_user(email=f"{name}-reference@example.test")
            setattr(cls, name, user)
            Membership.objects.create(organization=org, user=user, role=role)
        cls.contact = Contact.objects.create(organization=cls.org, name="Cliente autorizado")
        cls.matter = Matter.objects.create(organization=cls.org, title="Pasta Civil", client=cls.contact, owner=cls.owner, area="civil")
        cls.secret = Matter.objects.create(organization=cls.org, title="Pasta reservada", owner=cls.owner, confidential=True)
        today = timezone.localdate()
        cls.task = Task.objects.create(organization=cls.org, matter=cls.matter, title="Entrega atrasada", owner=cls.owner, due_date=today-timedelta(days=1))
        cls.today_task = Task.objects.create(organization=cls.org, title="Entrega hoje", owner=cls.viewer, due_date=today)
        Task.objects.create(organization=cls.org, matter=cls.secret, title="Entrega sigilosa", owner=cls.owner, due_date=today-timedelta(days=2))
        Task.objects.create(organization=cls.org, title="Conclusão registrada", owner=cls.owner, due_date=today-timedelta(days=10), status="done", completed_at=timezone.now(), completion_note="Entregue")
        Task.objects.create(organization=cls.org, title="Conclusão legada", owner=cls.owner, due_date=today, status="done", completion_note="Histórico")
        cls.opportunity = Opportunity.objects.create(organization=cls.org, contact=cls.contact, owner=cls.owner, title="Consulta comercial", amount=Decimal("900.00"), next_action="   ")
        Opportunity.objects.create(organization=cls.org, contact=cls.contact, owner=cls.viewer, title="Proposta enviada", stage="proposal", amount=Decimal("1800.00"), next_action="Retornar")
        Opportunity.objects.create(organization=cls.org, contact=cls.contact, owner=cls.owner, title="Atendimento ganho", stage="won", amount=Decimal("3000.00"))
        foreign = Contact.objects.create(organization=cls.other, name="Contato externo")
        Opportunity.objects.create(organization=cls.other, contact=foreign, owner=cls.outsider, title="Oportunidade externa", amount=Decimal("99000.00"))

    def setUp(self):
        self.client.force_login(self.viewer)

    def board(self, **params):
        return self.client.get(reverse("legal:kanban"), params)

    def crm(self, **params):
        return self.client.get(reverse("legal:list", args=["crm"]), params)

    def test_task_metrics_use_sigilo_and_real_completion_dates(self):
        response = self.board()
        self.assertEqual([m["value"] for m in response.context["task_metrics"]], [2, 1, 1])
        self.assertNotContains(response, "Entrega sigilosa")
        done = self.board(period="completed_month")
        self.assertContains(done, "Conclusão registrada")
        self.assertNotContains(done, "Conclusão legada")
        self.assertEqual(sum(c["count"] for c in done.context["columns"]), 1)
        self.assertEqual([m["value"] for m in done.context["task_metrics"]], [2, 1, 1])

    def test_task_attention_filters_and_metrics_preserve_owner(self):
        response = self.board(owner=self.viewer.pk, period="today")
        self.assertContains(response, "Entrega hoje")
        self.assertNotContains(response, "Entrega atrasada")
        self.assertEqual([m["value"] for m in response.context["task_metrics"]], [1, 0, 0])
        for metric in response.context["task_metrics"]:
            self.assertEqual(parse_qs(urlparse(metric["url"]).query)["owner"], [str(self.viewer.pk)])

    def test_invalid_board_filters_do_not_widen_scope(self):
        for params in [dict(owner=self.outsider.pk), dict(owner="9"*5000), dict(owner=self.portal.pk), dict(priority="invalid"), dict(niche="criminal"), dict(period="invalid"), dict(q="x"*121)]:
            with self.subTest(params=params):
                response = self.board(**params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(sum(c["count"] for c in response.context["columns"]), 0)
        self.assertNotContains(self.board(), self.portal.email)

    def test_crm_totals_count_all_filtered_records_and_not_other_office(self):
        response = self.crm()
        self.assertEqual([m["value"] for m in response.context["module_stats"]], [2, 1, 1])
        columns = {c["key"]: c for c in response.context["pipeline"]}
        self.assertEqual(columns["new"]["amount"], "R$ 900,00")
        self.assertNotContains(response, "Oportunidade externa")
        self.assertTrue(all(not row["edit_url"] for row in response.context["module_rows"]))
        self.assertNotContains(response, reverse("legal:edit", args=["crm", self.opportunity.pk]))

    def test_no_action_recognizes_whitespace_and_excludes_closed_work(self):
        response = self.crm(focus="no_action", view="list")
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertContains(response, "Consulta comercial")
        self.assertNotContains(response, "Atendimento ganho")
        self.assertContains(response, 'class="relationship-list"')

    def test_crm_metric_targets_match_counts_and_filtered_empty_is_explained(self):
        response = self.crm(status="won", focus="won")
        self.assertEqual([m["value"] for m in response.context["module_stats"]], [2, 1, 1])
        for metric in response.context["module_stats"]:
            linked = self.client.get(metric["url"])
            self.assertEqual(linked.context["page_obj"].paginator.count, metric["value"])
        empty = self.crm(owner=self.viewer.pk, focus="won")
        self.assertContains(empty, "Nenhum resultado com estes filtros")
        self.assertNotContains(empty, "Abra a primeira oportunidade")

    def test_crm_owner_sort_and_pagination_preserve_filters(self):
        for i in range(26):
            Opportunity.objects.create(organization=self.org, contact=self.contact, owner=self.owner, title=f"Novo {i}", amount=Decimal("1.00"))
        response = self.crm(owner=self.owner.pk, sort="amount", focus="open", view="list")
        self.assertEqual(response.context["page_obj"].paginator.count, 27)
        self.assertEqual(response.context["module_rows"][0]["record"], self.opportunity)
        self.assertIn("owner="+str(self.owner.pk), response.context["pagination_query"])
        self.assertIn("view=list", response.context["pagination_query"])
        self.assertEqual(sum(c["total"] for c in response.context["pipeline"]), 27)
        self.assertEqual(sum(len(c["rows"]) for c in response.context["pipeline"]), 25)

    def test_invalid_crm_filters_return_empty_400(self):
        for params in [dict(owner=self.outsider.pk), dict(owner=self.portal.pk), dict(status="invalid"), dict(sort="title;drop"), dict(focus="invalid"), dict(view="other"), dict(niche="invalid")]:
            with self.subTest(params=params):
                response = self.crm(**params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_portal_role_cannot_read_internal_workflows(self):
        self.client.force_login(self.portal)
        self.assertEqual(self.board().status_code, 403)
        self.assertEqual(self.crm().status_code, 403)
