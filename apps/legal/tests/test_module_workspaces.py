from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization
from apps.legal.models import Contact, Deadline, FinanceEntry, Matter, Opportunity
from apps.legal.services import record_payment, reverse_payment


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class ModuleWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Workspace modules", slug="workspace-modules", business_type="office")
        cls.owner = get_user_model().objects.create_user(email="modules-owner@example.test", password="test-only-password")
        cls.viewer = get_user_model().objects.create_user(email="modules-viewer@example.test", password="test-only-password")
        Membership.objects.create(organization=cls.org, user=cls.owner, role="owner")
        Membership.objects.create(organization=cls.org, user=cls.viewer, role="viewer")
        cls.contact = Contact.objects.create(organization=cls.org, name="Pessoa dos módulos")
        cls.matter = Matter.objects.create(organization=cls.org, title="Demanda autorizada", owner=cls.owner, client=cls.contact)
        cls.secret = Matter.objects.create(organization=cls.org, title="Demanda restrita", owner=cls.owner, confidential=True)

    def setUp(self):
        self.client.force_login(self.owner)

    def screen(self, module, **filters):
        return self.client.get(reverse("legal:list", args=[module]), filters)

    def test_each_workspace_has_its_own_template_and_creation_label(self):
        for module in ["matters", "contacts", "cases", "deadlines", "documents", "finance", "crm"]:
            with self.subTest(module=module):
                response = self.screen(module)
                self.assertEqual(response.status_code, 200)
                expected = {"contacts": "legal/contact_directory.html", "cases": "legal/case_directory.html"}.get(module, f"legal/modules/{module}.html")
                self.assertEqual(response.context["module_template"], expected)
                self.assertTemplateUsed(response, expected if module in {"contacts", "cases"} else "legal/list.html")
                self.assertNotContains(response, "Exportar dados")
                self.assertNotContains(response, "Novo registro")

    def test_filtered_metrics_do_not_include_inaccessible_matters(self):
        self.client.force_login(self.viewer)
        response = self.screen("matters")
        self.assertEqual(response.context["module_stats"][0]["value"], 1)
        self.assertEqual(len(response.context["module_rows"]), 1)
        self.assertNotContains(response, self.secret.title)
        self.assertNotContains(response, "Nova pasta")
        self.assertNotContains(response, "/editar/")
        filtered = self.screen("matters", q="inexistente")
        self.assertEqual(filtered.context["module_stats"][0]["value"], 0)
        self.assertContains(filtered, "Nenhum resultado com estes filtros")

    def test_deadline_counts_use_filtered_scope_and_real_dates(self):
        today = timezone.localdate()
        for matter, days in [(self.matter, -1), (self.matter, 4), (self.secret, -2)]:
            Deadline.objects.create(organization=self.org, matter=matter, owner=self.owner, title=f"Prazo {days}", source="Origem identificada", due_date=today + timedelta(days=days))
        self.client.force_login(self.viewer)
        response = self.screen("deadlines")
        stats = {s["key"]: s["value"] for s in response.context["module_stats"]}
        self.assertEqual(stats, {"pending": 2, "overdue": 1, "soon": 1})
        self.assertNotContains(response, "Conferir</a>")
        self.assertNotContains(response, "Prazo -2")

    def test_financial_totals_separate_client_money_and_subtract_reversals(self):
        entries = []
        for kind, amount in [("income", "100.00"), ("expense", "40.00"), ("client_fund", "800.00")]:
            entries.append(FinanceEntry.objects.create(organization=self.org, matter=self.matter, kind=kind, amount=Decimal(amount), description=kind, due_date=timezone.localdate()))
        income, expense, client_fund = entries
        payment = record_payment(entry=income, actor=self.owner, amount=Decimal("30.00"), date=timezone.localdate(), note="Baixa conferida")
        reverse_payment(payment=payment, actor=self.owner, note="Correção da baixa", date=timezone.localdate())
        record_payment(entry=income, actor=self.owner, amount=Decimal("20.00"), date=timezone.localdate(), note="Baixa correta")
        record_payment(entry=client_fund, actor=self.owner, amount=Decimal("500.00"), date=timezone.localdate(), note="Movimentação de cliente")
        totals = {item["key"]: item for item in self.screen("finance").context["finance_totals"]}
        self.assertEqual(totals["income"]["forecast"], "R$ 100,00")
        self.assertEqual(totals["income"]["moved"], "R$ 20,00")
        self.assertEqual(totals["income"]["balance"], "R$ 80,00")
        self.assertEqual(totals["client_fund"]["moved"], "R$ 500,00")
        filtered = {item["key"]: item for item in self.screen("finance", status="expense").context["finance_totals"]}
        self.assertEqual(filtered["income"]["forecast"], "R$ 0,00")
        self.assertEqual(filtered["expense"]["forecast"], "R$ 40,00")

    def test_crm_pagination_does_not_claim_page_totals_as_workspace_totals(self):
        for index in range(26):
            Opportunity.objects.create(organization=self.org, contact=self.contact, owner=self.owner, title=f"Proposta {index:02}", stage="proposal", next_action="Retornar contato")
        response = self.screen("crm")
        self.assertEqual(response.context["module_stats"][0]["value"], 26)
        self.assertEqual(sum(len(column["rows"]) for column in response.context["pipeline"]), 25)
        self.assertContains(response, "Colunas mostram os registros desta página.")
        self.assertEqual(len(self.screen("crm", page=2).context["module_rows"]), 1)

    def test_finance_remains_forbidden_to_viewer(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.screen("finance").status_code, 403)

    @override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
    def test_finance_query_count_does_not_grow_per_entry(self):
        from apps.billing.models import OrganizationSubscription
        OrganizationSubscription.objects.create(organization=self.org, plan="max", status="active")
        def add_entry(index):
            FinanceEntry.objects.create(organization=self.org, matter=self.matter, kind="income", amount=Decimal("100.00"), description=f"Entrada {index}", due_date=timezone.localdate())
        add_entry(0)
        with CaptureQueriesContext(connection) as initial:
            self.assertEqual(self.screen("finance").status_code, 200)
        for index in range(1, 15):
            add_entry(index)
        with CaptureQueriesContext(connection) as expanded:
            self.assertEqual(self.screen("finance").status_code, 200)
        self.assertLessEqual(len(expanded), len(initial) + 1)
