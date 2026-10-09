from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization, User
from apps.core.test_platform import TEST_SETTINGS
from apps.legal.models import AuditEvent, FinanceEntry, Matter, Payment, Task
from apps.legal.services import complete_task, record_payment, reverse_payment
from .models import Goal, GoalUpdate
from .services import dashboard_goals, goal_progress, record_progress, save_goal, visible_goals


@override_settings(**TEST_SETTINGS)
class PerformanceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.org = Organization.objects.create(name="Metas", slug="goals", business_type="office", practice_areas=["civil", "familia", "trabalhista"])
        self.other_org = Organization.objects.create(name="Outro", slug="other-goals", business_type="office")
        self.owner = User.objects.create_user("owner@goals.test", "SecureForTests!537")
        self.viewer = User.objects.create_user("viewer@goals.test", "SecureForTests!538")
        self.outsider = User.objects.create_user("outside@goals.test", "SecureForTests!539")
        Membership.objects.create(organization=self.org, user=self.owner, role="owner")
        Membership.objects.create(organization=self.org, user=self.viewer, role="viewer")
        Membership.objects.create(organization=self.other_org, user=self.outsider, role="owner")
        self.data = {"title": "Meta mensal", "description": "Registro de evolução", "metric": "manual", "target": Decimal("10"), "starts_on": self.today - timedelta(days=7), "ends_on": self.today + timedelta(days=7), "owner": None, "niche": "", "archived": False}

    def goal(self, **changes):
        return save_goal(actor=self.owner, organization=self.org, data={**self.data, **changes})

    def login(self, user):
        self.client.force_login(user)

    def test_manager_forms_persist_progress_and_evidence_with_immutable_history(self):
        self.login(self.owner)
        payload = {**self.data, "owner": "", "starts_on": self.data["starts_on"].isoformat(), "ends_on": self.data["ends_on"].isoformat(), "archived": ""}
        self.assertContains(self.client.get(reverse("performance:create")), "Nova meta")
        self.assertRedirects(self.client.post(reverse("performance:create"), payload), reverse("performance:list"))
        goal = Goal.objects.get()
        response = self.client.post(reverse("performance:progress", args=[goal.pk]), {"value": "4.50", "note": "Relatório de atendimentos conferido"})
        self.assertRedirects(response, reverse("performance:list"))
        goal.refresh_from_db()
        self.assertEqual(goal.manual_value, Decimal("4.50"))
        self.assertEqual(GoalUpdate.objects.get().previous_value, Decimal("0"))
        self.assertEqual(dashboard_goals(self.owner, self.org)[0]["percent"], 45)
        self.assertContains(self.client.get(reverse("performance:progress", args=[goal.pk])), "Relatório de atendimentos conferido")
        with self.assertRaises(ValidationError):
            GoalUpdate.objects.get().save()

    def test_viewer_and_other_tenant_cannot_mutate_or_read_other_goals(self):
        goal = self.goal()
        self.login(self.viewer)
        self.assertContains(self.client.get(reverse("performance:list")), goal.title)
        for name, args in [("create", []), ("edit", [goal.pk]), ("progress", [goal.pk])]:
            self.assertEqual(self.client.post(reverse(f"performance:{name}", args=args), {}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            record_progress(actor=self.viewer, organization=self.org, goal_id=goal.pk, value="3", note="Teste")
        self.login(self.outsider)
        self.assertNotContains(self.client.get(reverse("performance:list")), goal.title)
        self.assertEqual(self.client.get(reverse("performance:edit", args=[goal.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("performance:progress", args=[goal.pk]), {"value": 99, "note": "Teste"}).status_code, 404)
        self.assertFalse(visible_goals(self.outsider, self.org).exists())

    def test_validation_of_period_target_responsible_niche_and_manual_update(self):
        for changes in [{"target": Decimal("0")}, {"ends_on": self.today - timedelta(days=8)}, {"owner": self.outsider}, {"metric": "tasks", "target": Decimal("1.5")}, {"niche": "criminal"}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.goal(**changes)
        goal = self.goal()
        for value, note in [("-1", "Motivo"), ("NaN", "Motivo"), ("1.001", "Motivo"), ("3", "")]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                record_progress(actor=self.owner, organization=self.org, goal_id=goal.pk, value=value, note=note)
        self.assertFalse(GoalUpdate.objects.exists())
        self.assertEqual(Goal.objects.get(pk=goal.pk).manual_value, 0)
        self.login(self.owner)
        self.assertEqual(self.client.get(reverse("performance:list"), {"niche": "invalid"}).status_code, 404)

    def test_task_metric_uses_real_completion_date_and_filters_private_and_niche(self):
        civil = Matter.objects.create(organization=self.org, title="Civil", area="civil", owner=self.owner)
        secret = Matter.objects.create(organization=self.org, title="Sigilosa", area="civil", owner=self.owner, confidential=True)
        for matter in [civil, secret]:
            task = Task.objects.create(organization=self.org, matter=matter, title="Concluir", owner=self.owner, due_date=self.today)
            complete_task(task=task, actor=self.owner, evidence="Entregue")
        # Historical completion with no evidence of its date must not be invented.
        Task.objects.create(organization=self.org, matter=civil, title="Legado sem data", owner=self.owner, due_date=self.today, status="done", completion_note="Legado")
        goal = self.goal(metric="tasks", niche="civil")
        self.assertEqual(goal_progress(goal, self.owner), 2)
        self.assertEqual(goal_progress(goal, self.viewer), 1)
        self.assertEqual(len(dashboard_goals(self.owner, self.org, niche="civil")), 1)
        self.assertEqual(dashboard_goals(self.owner, self.org, niche="familia"), [])

    def test_matter_metric_accepts_legacy_label_and_respects_owner_and_tenant(self):
        for area in ["civil", "Direito Civil", "familia"]:
            Matter.objects.create(organization=self.org, title=area, area=area, owner=self.owner)
        Matter.objects.create(organization=self.other_org, title="Outro escritório", area="civil", owner=self.outsider)
        self.assertEqual(goal_progress(self.goal(metric="matters", niche="civil", owner=self.owner), self.owner), 2)

    def test_legacy_task_uses_audited_completion_and_outside_period_is_excluded(self):
        task = Task.objects.create(organization=self.org, title="Conclusão antiga", owner=self.owner, due_date=self.today, status="done", completion_note="Arquivo de entrega")
        goal = self.goal(metric="tasks")
        self.assertEqual(goal_progress(goal, self.owner), 0)
        AuditEvent.objects.create(organization=self.org, actor=self.owner, action="task.completed", object_type="legal.task", object_id=str(task.pk), description="Entrega comprovada")
        self.assertEqual(goal_progress(goal, self.owner), 1)
        older_goal = self.goal(metric="tasks", starts_on=self.today - timedelta(days=60), ends_on=self.today - timedelta(days=30))
        self.assertEqual(goal_progress(older_goal, self.owner), 0)

    def test_csrf_is_required_and_get_never_records_progress(self):
        goal = self.goal()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        url = reverse("performance:progress", args=[goal.pk])
        self.assertEqual(client.get(url, {"value": "9", "note": "Tentativa via GET"}).status_code, 200)
        self.assertEqual(client.post(url, {"value": "9", "note": "Sem CSRF"}).status_code, 403)
        self.assertFalse(GoalUpdate.objects.exists())
        goal.refresh_from_db()
        self.assertEqual(goal.manual_value, 0)

    def test_revenue_is_net_and_only_available_to_manager_on_max(self):
        goal = self.goal(metric="revenue", target=Decimal("1000"))
        entry = FinanceEntry.objects.create(organization=self.org, description="Honorários", kind="income", amount=1000, due_date=self.today)
        payment = record_payment(entry=entry, actor=self.owner, amount="400", date=self.today, note="Recebido")
        self.assertEqual(goal_progress(goal, self.owner), 400)
        reverse_payment(payment=payment, actor=self.owner, note="Cancelamento", date=self.today)
        self.assertEqual(goal_progress(goal, self.owner), 0)
        self.assertFalse(visible_goals(self.viewer, self.org).filter(pk=goal.pk).exists())
        with override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            subscription = OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
            self.assertFalse(visible_goals(self.owner, self.org).filter(pk=goal.pk).exists())
            with self.assertRaises(PermissionDenied):
                self.goal(metric="revenue")
            subscription.plan = "max"
            subscription.save()
            self.assertEqual(goal_progress(goal, self.owner), 0)
            subscription.status = "suspended"
            subscription.save()
            self.login(self.owner)
            self.assertIn(self.client.get(reverse("performance:list")).status_code, [302, 403])

    def test_revenue_owner_receives_adjustment_when_another_manager_reverses_payment(self):
        manager = User.objects.create_user("reversal-manager@goals.test", "SecureForTests!782")
        Membership.objects.create(organization=self.org, user=manager, role="manager")
        owner_goal = self.goal(metric="revenue", owner=self.owner, target=Decimal("1000"))
        manager_goal = self.goal(metric="revenue", owner=manager, target=Decimal("1000"))
        entry = FinanceEntry.objects.create(organization=self.org, description="Receita por responsável", kind="income", amount=1000, due_date=self.today)
        payment = record_payment(entry=entry, actor=self.owner, amount="400", date=self.today, note="Recebimento registrado pela direção")
        self.assertEqual(goal_progress(owner_goal, self.owner), 400)
        self.assertEqual(goal_progress(manager_goal, manager), 0)
        reverse_payment(payment=payment, actor=manager, note="Estorno conferido por outra pessoa", date=self.today)
        self.assertEqual(goal_progress(owner_goal, self.owner), 0)
        self.assertEqual(goal_progress(manager_goal, manager), 0)
