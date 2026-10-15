from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.core.models import Membership, Organization
from apps.billing.models import OrganizationSubscription
from apps.legal.models import Appointment, AuditEvent, Deadline, FinanceEntry, Matter, Task
from apps.legal.services import move_task, record_payment, reverse_payment


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class KanbanDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Quadro Alfa", slug="quadro-alfa", business_type="office", practice_areas=["civil", "familia", "trabalhista"])
        cls.other = Organization.objects.create(name="Quadro Beta", slug="quadro-beta", business_type="office")
        cls.owner = get_user_model().objects.create_user(email="board-owner@example.test", password="test-board-only")
        cls.viewer = get_user_model().objects.create_user(email="board-viewer@example.test", password="test-board-only")
        cls.outsider = get_user_model().objects.create_user(email="board-other@example.test", password="test-board-only")
        for org,user,role in [(cls.org,cls.owner,"owner"),(cls.org,cls.viewer,"viewer"),(cls.other,cls.outsider,"owner")]:
            Membership.objects.create(organization=org,user=user,role=role)
        cls.matter = Matter.objects.create(organization=cls.org,title="Pasta Civil permitida",area="civil",owner=cls.owner)
        cls.secret = Matter.objects.create(organization=cls.org,title="Pasta confidencial reservada",owner=cls.owner,confidential=True)
        cls.task = Task.objects.create(organization=cls.org,matter=cls.matter,title="Revisar entrevista",owner=cls.owner,due_date=timezone.localdate())
        cls.private_task = Task.objects.create(organization=cls.org,matter=cls.secret,title="Tarefa sigilosa reservada",owner=cls.owner,due_date=timezone.localdate())
        cls.foreign_task = Task.objects.create(organization=cls.other,title="Tarefa de Beta",owner=cls.outsider,due_date=timezone.localdate())
        cls.deadline = Deadline.objects.create(organization=cls.org,matter=cls.matter,title="Obrigação independente",source="Fonte humana",owner=cls.owner,due_date=timezone.localdate())

    def setUp(self):
        self.client.force_login(self.owner)

    def post_move(self, target, current, note=""):
        return self.client.post(reverse("legal:kanban_move",args=[self.task.pk]),{"destination":target,"expected_status":current,"note":note},HTTP_ACCEPT="application/json")

    def test_create_from_column_uses_initial_stage_without_bypassing_completion(self):
        url = reverse("legal:create", args=["tasks"])
        response = self.client.get(url + "?status=doing")
        self.assertEqual(response.context["form"]["initial_status"].value(), "doing")
        data = {"title": "Cadastro na etapa", "owner": self.owner.pk, "due_date": timezone.localdate(), "priority": "normal", "initial_status": "doing"}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        task = Task.objects.get(title="Cadastro na etapa")
        self.assertEqual(task.status, "doing")
        self.assertTrue(AuditEvent.objects.filter(action="task.moved", object_id=str(task.pk)).exists())
        response = self.client.post(url, dict(data, title="Conclusão indevida", initial_status="done"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(title="Conclusão indevida").exists())
        self.assertNotIn("initial_status", self.client.get(reverse("legal:edit", args=["tasks", task.pk])).context["form"].fields)

    def test_move_completion_reopening_and_deadline_independence(self):
        self.assertEqual(self.post_move("doing","todo").status_code,200)
        self.assertEqual(self.post_move("done","doing").status_code,400)
        self.assertEqual(self.post_move("done","doing","Peça conferida com cliente.").status_code,200)
        self.task.refresh_from_db();self.deadline.refresh_from_db()
        self.assertEqual(self.task.status,"done")
        self.assertIsNotNone(self.task.completed_at)
        self.assertEqual(self.deadline.status,"pending")
        self.assertEqual(self.post_move("todo","done").status_code,400)
        self.assertEqual(self.post_move("todo","done","Cliente pediu revisão.").status_code,200)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.completed_at)
        self.assertEqual(self.task.completion_note,"")
        self.assertTrue(AuditEvent.objects.filter(action="task.completed",object_id=str(self.task.pk)).exists())

    def test_stale_move_is_rejected_without_overwriting(self):
        move_task(task=self.task,actor=self.owner,destination="doing",expected_status="todo")
        response=self.post_move("done","todo","Evidência")
        self.assertEqual(response.status_code,400)
        self.task.refresh_from_db();self.assertEqual(self.task.status,"doing")

    def test_all_working_stages_cancel_and_reactivate_are_audited(self):
        current = "todo"
        for destination in ["doing", "in_review", "blocked"]:
            self.assertEqual(self.post_move(destination, current).status_code, 200)
            current = destination
        self.assertEqual(self.post_move("cancelled", current, "  ").status_code, 400)
        self.assertEqual(self.post_move("cancelled", current, "Demanda encerrada pelo cliente.").status_code, 200)
        cancellation = AuditEvent.objects.get(action="task.cancelled", object_id=str(self.task.pk))
        self.assertIn("Demanda encerrada", cancellation.description)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.completed_at)
        self.assertEqual(self.post_move("todo", "cancelled").status_code, 400)
        self.assertEqual(self.post_move("todo", "cancelled", "Cliente retomou a solicitação.").status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(action="task.reopen", object_id=str(self.task.pk), description__contains="retomou").exists())
        count = AuditEvent.objects.filter(object_type="legal.task", object_id=str(self.task.pk)).count()
        self.assertEqual(self.post_move("todo", "todo").status_code, 200)
        self.assertEqual(AuditEvent.objects.filter(object_type="legal.task", object_id=str(self.task.pk)).count(), count)

    def test_four_display_groups_preserve_all_six_real_stages_without_duplicates(self):
        expected_ids = {self.task.pk, self.private_task.pk}
        for status in Task.Status.values:
            for offset in [-1, 1]:
                item = Task.objects.create(organization=self.org, matter=self.matter, title=f"Etapa {status} {offset}",
                    owner=self.owner, due_date=timezone.localdate() + timedelta(days=offset), status=status,
                    completion_note="Entrega conferida." if status == "done" else "")
                expected_ids.add(item.pk)
        response = self.client.get(reverse("legal:kanban"))
        columns = {column["code"]: column for column in response.context["columns"]}
        self.assertEqual(list(columns), ["overdue", "todo", "doing", "done"])
        displayed = [task.pk for column in columns.values() for task in column["tasks"]]
        self.assertCountEqual(displayed, expected_ids)
        self.assertEqual({task.status for task in columns["doing"]["tasks"]}, {"doing", "in_review", "blocked"})
        self.assertEqual({task.status for task in columns["done"]["tasks"]}, {"done", "cancelled"})
        self.assertEqual(columns["overdue"]["count"], 4)

    def test_truncated_column_links_to_all_matching_tasks_with_filters_and_pagination(self):
        Task.objects.bulk_create([Task(organization=self.org, matter=self.matter, title=f"Fila extensa {index}",
            owner=self.owner, priority="urgent", due_date=timezone.localdate()) for index in range(105)])
        filters = {"q": "Fila extensa", "owner": str(self.owner.pk), "priority": "urgent", "niche": "civil", "period": "week"}
        response = self.client.get(reverse("legal:kanban"), filters)
        column = next(column for column in response.context["columns"] if column["code"] == "todo")
        self.assertEqual(column["count"], 105)
        self.assertEqual(len(column["tasks"]), 100)
        self.assertTrue(column["truncated"])
        self.assertTrue(response.context["has_active_filters"])
        listing = self.client.get(column["list_url"])
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.context["page_obj"].paginator.count, 105)
        self.assertTrue(listing.context["task_filter_form"].is_valid())
        self.assertIn("board_group=todo", listing.context["pagination_query"])
        last_page = self.client.get(column["list_url"] + "&page=5")
        self.assertEqual(len(last_page.context["page_obj"]), 5)
        self.assertNotContains(last_page, self.foreign_task.title)
        for key in filters:
            self.assertIn(key + "=", last_page.context["pagination_query"])

    def test_task_filters_validate_owner_stage_and_group_without_leaking_results(self):
        for url, filters in [
            (reverse("legal:kanban"), {"owner": str(self.outsider.pk)}),
            (reverse("legal:list", args=["tasks"]), {"owner": str(self.outsider.pk)}),
            (reverse("legal:list", args=["tasks"]), {"board_group": "foreign"}),
            (reverse("legal:list", args=["tasks"]), {"status": "foreign"}),
        ]:
            with self.subTest(url=url, filters=filters):
                response = self.client.get(url, filters)
                self.assertEqual(response.status_code, 400)
                self.assertNotContains(response, self.task.title, status_code=400)
                self.assertNotContains(response, self.foreign_task.title, status_code=400)
        response = self.client.get(reverse("legal:kanban"), {"period": "week"})
        self.assertTrue(response.context["has_active_filters"])
        self.assertFalse(self.client.get(reverse("legal:kanban")).context["has_active_filters"])

    def test_search_by_matter_title_matches_board_and_complete_column_listing(self):
        Task.objects.bulk_create([Task(organization=self.org, matter=self.matter, title=f"Entrega vinculada {index}",
            owner=self.owner, due_date=timezone.localdate()) for index in range(100)])
        filters = {"q": self.matter.title, "niche": "civil", "owner": str(self.owner.pk)}
        board = self.client.get(reverse("legal:kanban"), filters)
        column = next(column for column in board.context["columns"] if column["code"] == "todo")
        self.assertTrue(column["truncated"])
        self.assertEqual(column["count"], 101)
        self.assertEqual(len(column["tasks"]), 100)
        listing = self.client.get(column["list_url"])
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.context["page_obj"].paginator.count, column["count"])
        self.assertIn(self.task, listing.context["page_obj"])
        final_page = self.client.get(column["list_url"] + "&page=5")
        self.assertEqual(len(final_page.context["page_obj"]), 1)
        self.assertNotContains(final_page, self.private_task.title)
        self.assertNotContains(final_page, self.foreign_task.title)

    def test_task_modal_save_returns_json_and_invalid_fields_keep_html_errors(self):
        url = reverse("legal:create", args=["tasks"])
        data = {"title": "Cadastro por modal", "owner": self.owner.pk, "matter": self.matter.pk,
                "due_date": timezone.localdate(), "priority": "high", "initial_status": "in_review"}
        created = self.client.post(url, data, HTTP_ACCEPT="application/json")
        self.assertEqual(created.status_code, 200)
        task = Task.objects.get(pk=created.json()["id"])
        self.assertEqual(created.json(), {"ok": True, "id": task.pk})
        self.assertEqual(task.organization, self.org)
        self.assertEqual(task.status, "in_review")
        edited = self.client.post(reverse("legal:edit", args=["tasks", task.pk]), dict(data, title="Edição por modal"), HTTP_ACCEPT="application/json")
        self.assertEqual(edited.json(), {"ok": True, "id": task.pk})
        task.refresh_from_db()
        self.assertEqual(task.title, "Edição por modal")
        self.assertEqual(task.status, "in_review")
        invalid = self.client.post(url, dict(data, title="", owner=self.outsider.pk), HTTP_ACCEPT="application/json")
        self.assertEqual(invalid.status_code, 200)
        self.assertIn("text/html", invalid.headers["Content-Type"])
        self.assertIn("owner", invalid.context["form"].errors)
        self.assertIn("title", invalid.context["form"].errors)
        self.assertEqual(Task.objects.filter(title="Cadastro por modal").count(), 0)
        self.assertEqual(self.client.post(reverse("legal:edit", args=["tasks", self.foreign_task.pk]), data, HTTP_ACCEPT="application/json").status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(url, data, HTTP_ACCEPT="application/json").status_code, 403)
        self.assertEqual(csrf_client.post(reverse("legal:edit", args=["tasks", task.pk]), data, HTTP_ACCEPT="application/json").status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(url, data, HTTP_ACCEPT="application/json").status_code, 403)
        self.assertEqual(self.client.post(reverse("legal:edit", args=["tasks", task.pk]), data, HTTP_ACCEPT="application/json").status_code, 403)
        task.refresh_from_db()
        self.assertEqual(task.title, "Edição por modal")

    def test_list_reactivation_uses_the_same_audited_service(self):
        self.assertEqual(self.post_move("cancelled", "todo", "Solicitação suspensa pelo cliente.").status_code, 200)
        url = reverse("legal:action", args=["tasks", self.task.pk, "reopen"])
        self.assertEqual(self.client.post(url, {"reason": ""}).status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "cancelled")
        self.assertEqual(self.client.post(url, {"reason": "Cliente confirmou a retomada."}).status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "todo")
        self.assertTrue(AuditEvent.objects.filter(action="task.reopen", object_id=str(self.task.pk), description__contains="retomada").exists())

    def test_get_does_not_mutate_and_fallback_form_works(self):
        self.assertEqual(self.client.get(reverse("legal:kanban_move",args=[self.task.pk])).status_code,200)
        self.task.refresh_from_db();self.assertEqual(self.task.status,"todo")
        response=self.client.post(reverse("legal:kanban_move",args=[self.task.pk]),{"destination":"doing","expected_status":"todo"})
        self.assertRedirects(response,reverse("legal:kanban"))

    def test_foreign_and_confidential_tasks_cannot_be_moved_or_seen(self):
        self.assertEqual(self.client.get(reverse("legal:kanban_move",args=[self.foreign_task.pk])).status_code,404)
        self.client.force_login(self.viewer)
        board=self.client.get(reverse("legal:kanban"))
        self.assertNotContains(board,self.private_task.title)
        self.assertNotContains(board,self.foreign_task.title)
        self.assertNotContains(board,'data-move-button')
        self.assertEqual(self.post_move("doing","todo").status_code,403)
        dashboard=self.client.get(reverse("legal:dashboard"))
        self.assertNotContains(dashboard,self.secret.title)
        self.assertNotContains(dashboard,self.private_task.title)

    def test_overdue_lane_derived_without_changing_status(self):
        self.task.due_date=timezone.localdate()-timedelta(days=1);self.task.save()
        columns=self.client.get(reverse("legal:kanban")).context["columns"]
        self.assertIn(self.task,[task for task in columns[0]["tasks"]])
        self.assertNotIn(self.task,[task for task in columns[1]["tasks"]])
        self.task.refresh_from_db();self.assertEqual(self.task.status,"todo")

    def test_niche_filter_applies_to_dashboard_board_and_lists(self):
        family=Matter.objects.create(organization=self.org,title="Inventário familiar",area="Família e Sucessões",owner=self.owner)
        Task.objects.create(organization=self.org,matter=family,title="Tarefa familiar exclusiva",owner=self.owner,due_date=timezone.localdate())
        for url in [reverse("legal:dashboard"),reverse("legal:kanban"),reverse("legal:list",args=["tasks"])]:
            response=self.client.get(url,{"niche":"civil"})
            self.assertContains(response,self.task.title)
            self.assertNotContains(response,"Tarefa familiar exclusiva")
        self.assertEqual(self.client.get(reverse("legal:dashboard"),{"niche":"familia"}).context["stats"]["matters"],1)
        self.assertEqual(self.client.get(reverse("legal:dashboard"),{"niche":"foreign"}).context["niche"],"")

    def test_csrf_protects_kanban_mutation(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.owner)
        self.assertEqual(client.post(reverse("legal:kanban_move",args=[self.task.pk]),{"destination":"doing","expected_status":"todo"}).status_code,403)

    def test_dashboard_calendar_navigation_and_empty_financial_safe(self):
        response=self.client.get(reverse("legal:dashboard"),{"month":"2027-02"})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context["calendar_month"].month,2)
        self.assertContains(response,"Metas de desempenho")
        self.assertContains(response,"Calendário do escritório")

    def test_additive_schema_accepts_inserts_from_previous_release(self):
        # During rolling replacement/rollback the v3 ORM omits the new columns.
        def legacy_insert(instance, omitted, **overrides):
            fields=[field for field in instance._meta.local_concrete_fields if not field.primary_key and field.name != omitted]
            values=[field.get_db_prep_save(overrides.get(field.name,getattr(instance,field.attname)),connection) for field in fields]
            table=connection.ops.quote_name(instance._meta.db_table)
            columns=','.join(connection.ops.quote_name(field.column) for field in fields)
            with connection.cursor() as cursor:
                cursor.execute(f"INSERT INTO {table} ({columns}) VALUES ({','.join(['%s']*len(values))})",values)
        legacy_insert(self.org,"practice_areas",slug="legacy-default-compatible",name="Compatibilidade")
        self.assertEqual(Organization.objects.get(slug="legacy-default-compatible").practice_areas,[])
        appointment=Appointment.objects.create(organization=self.org,title="Agenda moderna",starts_at=timezone.now(),ends_at=timezone.now()+timedelta(hours=1),owner=self.owner)
        legacy_insert(appointment,"kind",title="Agenda da release anterior")
        self.assertEqual(Appointment.objects.get(title="Agenda da release anterior").kind,"other")

    def test_dashboard_financial_totals_subtract_reversals_and_separate_client_funds(self):
        OrganizationSubscription.objects.create(organization=self.org, plan="max", status="active")
        def entry(kind, amount):
            return FinanceEntry.objects.create(organization=self.org, matter=self.matter,
                description=kind, kind=kind, amount=Decimal(amount), due_date=timezone.localdate())
        income=entry("income", "1000")
        expense=entry("expense", "200")
        fund=entry("client_fund", "900")
        receipt=record_payment(entry=income, actor=self.owner, amount="350")
        payment=record_payment(entry=expense, actor=self.owner, amount="80")
        record_payment(entry=fund, actor=self.owner, amount="900")
        before=self.client.get(reverse("legal:dashboard")).context
        self.assertEqual(before["stats"]["receivable"], Decimal("650"))
        self.assertEqual(before["monthly_received"], Decimal("350"))
        self.assertEqual(before["monthly_expenses"], Decimal("80"))
        reverse_payment(payment=receipt, actor=self.owner, note="Baixa lançada por engano.")
        reverse_payment(payment=payment, actor=self.owner, note="Pagamento cancelado.")
        after=self.client.get(reverse("legal:dashboard")).context
        self.assertEqual(after["stats"]["receivable"], Decimal("1000"))
        self.assertEqual(after["monthly_received"], Decimal("0"))
        self.assertEqual(after["monthly_expenses"], Decimal("0"))
