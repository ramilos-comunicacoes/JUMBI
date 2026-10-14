from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization, User
from apps.core.test_platform import TEST_SETTINGS
from apps.legal.models import AuditEvent, Deadline, Matter, Task
from .models import MatterChecklist, MatterComment, RoutineApplication, RoutineTemplate
from .services import (add_checklist, add_comment, apply_template, dashboard_routines, import_example,
    matter_context, save_template, set_checklist_status, visible_records, visible_templates)


@override_settings(**TEST_SETTINGS)
class RoutineTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.org = Organization.objects.create(name="Rotinas", slug="rotinas-test", business_type="office", practice_areas=["civil", "familia"])
        self.other_org = Organization.objects.create(name="Outro", slug="rotinas-other", business_type="office")
        self.owner = User.objects.create_user("owner@routines.test", "TestRoutine!234567")
        self.operator = User.objects.create_user("operator@routines.test", "TestRoutine!234568")
        self.viewer = User.objects.create_user("viewer@routines.test", "TestRoutine!234569")
        self.client_user = User.objects.create_user("client@routines.test", "TestRoutine!234570")
        self.other = User.objects.create_user("other@routines.test", "TestRoutine!234571")
        for user, role in [(self.owner, "owner"), (self.operator, "operator"), (self.viewer, "viewer"), (self.client_user, "client")]:
            Membership.objects.create(organization=self.org, user=user, role=role)
        Membership.objects.create(organization=self.other_org, user=self.other, role="owner")
        self.matter = Matter.objects.create(organization=self.org, title="Pasta civil", area="civil", owner=self.owner)
        self.secret = Matter.objects.create(organization=self.org, title="Pasta sigilosa", area="civil", owner=self.owner, confidential=True)
        self.data = {"title": "Rotina civil", "description": "Orientações internas", "niches": ["civil", "familia"],
            "tasks": ["Revisar documentos", "Preparar retorno"], "checklist": ["Conferir cadastro"],
            "documents": ["Comprovante de endereço"], "is_active": True}

    def template(self, **changes):
        return save_template(actor=self.owner, organization=self.org, data={**self.data, **changes})

    def apply(self, template=None, **changes):
        template = template or self.template()
        return apply_template(**{"actor": self.owner, "organization": self.org, "matter_id": self.matter.pk,
            "template_id": template.pk, "expected_version": template.version, "task_due_date": self.today, **changes})

    def test_apply_creates_real_tasks_checklist_and_snapshot_once_without_deadlines(self):
        template = self.template()
        application, created = self.apply(template)
        repeat, repeated = self.apply(template)
        self.assertTrue(created)
        self.assertFalse(repeated)
        self.assertEqual(application.pk, repeat.pk)
        self.assertEqual(Task.objects.count(), 2)
        self.assertEqual(MatterChecklist.objects.count(), 2)
        self.assertEqual(Task.objects.filter(owner=self.owner, due_date=self.today).count(), 2)
        self.assertFalse(Deadline.objects.exists())
        self.assertEqual(application.snapshot["tasks"], self.data["tasks"])
        self.assertEqual(set(application.task_ids), set(Task.objects.values_list("pk", flat=True)))
        self.assertTrue(AuditEvent.objects.filter(action="routine.applied", object_type="legal.matter", object_id=str(self.matter.pk)).exists())
        with self.assertRaises(ValidationError):
            application.save()

    def test_template_edit_preserves_applied_snapshot_and_detects_stale_editor(self):
        template = self.template()
        application, _ = self.apply(template)
        changed = save_template(actor=self.owner, organization=self.org, template_id=template.pk, expected_version=1,
            data={**self.data, "tasks": ["Nova tarefa"]})
        self.assertEqual(changed.version, 2)
        application.refresh_from_db()
        self.assertEqual(application.snapshot["tasks"], self.data["tasks"])
        with self.assertRaises(ValidationError):
            save_template(actor=self.owner, organization=self.org, template_id=template.pk, expected_version=1, data=self.data)
        another = Matter.objects.create(organization=self.org, title="Outra civil", area="civil", owner=self.owner)
        with self.assertRaises(ValidationError):
            self.apply(template, matter_id=another.pk)
        self.assertFalse(Task.objects.filter(matter=another).exists())

    def test_niche_mismatch_and_past_dates_and_closed_matter_are_rejected(self):
        template = self.template(niches=["familia"])
        for changes in [{}, {"task_due_date": self.today - timedelta(days=1)}, {"task_due_date": None}]:
            with self.assertRaises(ValidationError):
                self.apply(template, **changes)
        generic = self.template(niches=[])
        for due in [None, self.today - timedelta(days=1)]:
            with self.assertRaises(ValidationError):
                self.apply(generic, task_due_date=due)
        self.matter.status = "closed"
        self.matter.save()
        with self.assertRaises(ValidationError):
            self.apply(generic)
        self.assertFalse(RoutineApplication.objects.exists())

    def test_legacy_niche_label_and_checklist_only_template(self):
        self.matter.area = "Direito Civil"
        self.matter.save()
        application, created = self.apply(self.template(tasks=[]), task_due_date=None)
        self.assertTrue(created)
        self.assertIsNone(application.task_due_date)
        self.assertFalse(Task.objects.exists())

    def test_confidential_pasta_authorization_and_dashboard_never_leak(self):
        self.apply(matter_id=self.secret.pk)
        add_comment(actor=self.owner, matter=self.secret, body="Comentário sigiloso")
        self.assertEqual(dashboard_routines(self.viewer, self.org)["routine_pending_count"], 0)
        self.assertEqual(visible_records(self.viewer, self.org, MatterComment).count(), 0)
        with self.assertRaises(PermissionDenied):
            matter_context(self.viewer, self.org, self.secret)
        with self.assertRaises(PermissionDenied):
            add_comment(actor=self.operator, matter=self.secret, body="Tentativa")
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse("routines:matter", args=[self.secret.pk])).status_code, 404)
        self.secret.members.add(self.operator)
        self.assertEqual(self.client.get(reverse("routines:matter", args=[self.secret.pk])).status_code, 200)
        self.assertEqual(dashboard_routines(self.operator, self.org)["routine_pending_count"], 2)
        self.assertEqual(dashboard_routines(self.operator, self.org, niche="familia")["routine_pending_count"], 0)

    def test_viewer_and_client_cannot_mutate_even_calling_services_directly(self):
        template = self.template()
        for user in [self.viewer, self.client_user]:
            with self.subTest(user=user):
                for operation in [lambda: self.apply(template, actor=user),
                    lambda: add_comment(actor=user, matter=self.matter, body="Tentativa"),
                    lambda: add_checklist(actor=user, matter=self.matter, title="Tentativa"),
                    lambda: save_template(actor=user, organization=self.org, data=self.data)]:
                    with self.assertRaises(PermissionDenied):
                        operation()
        self.assertFalse(visible_templates(self.client_user, self.org).exists())
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("routines:list")).status_code, 200)
        self.assertEqual(self.client.post(reverse("routines:create"), self.data).status_code, 403)
        self.assertEqual(self.client.post(reverse("routines:detail", args=[template.pk]), {}).status_code, 403)

    def test_operator_can_apply_but_cannot_create_templates(self):
        template = self.template()
        self.apply(template, actor=self.operator)
        self.assertEqual(Task.objects.filter(owner=self.operator).count(), 2)
        with self.assertRaises(PermissionDenied):
            import_example(actor=self.operator, organization=self.org, key="acolhimento")
        with self.assertRaises(PermissionDenied):
            save_template(actor=self.operator, organization=self.org, data=self.data)

    def test_other_tenant_cannot_read_or_write_and_related_validation_rejects_mixed_tenants(self):
        template = self.template()
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse("routines:list")), template.title)
        self.assertEqual(self.client.get(reverse("routines:detail", args=[template.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("routines:matter", args=[self.matter.pk])).status_code, 404)
        with self.assertRaises(PermissionDenied):
            self.apply(template, actor=self.other)
        with self.assertRaises(ValidationError):
            MatterComment.objects.create(organization=self.other_org, matter=self.matter, created_by=self.other, body="Mistura")

    def test_suspended_subscription_denies_all_mutations_but_export_scope_remains(self):
        template = self.template()
        comment = add_comment(actor=self.owner, matter=self.matter, body="Histórico existente")
        with override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            subscription = OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
            self.apply(template)
            subscription.status = "suspended"
            subscription.save()
            for operation in [lambda: self.apply(template), lambda: add_comment(actor=self.owner, matter=self.matter, body="Novo"),
                lambda: save_template(actor=self.owner, organization=self.org, data=self.data)]:
                with self.assertRaises(PermissionDenied):
                    operation()
            self.assertTrue(visible_records(self.owner, self.org, MatterComment).filter(pk=comment.pk).exists())

    def test_historical_authors_remain_after_revocation_and_are_immutable(self):
        item = add_checklist(actor=self.operator, matter=self.matter, title="Conferência antiga")
        comment = add_comment(actor=self.operator, matter=self.matter, body="Comentário original")
        Membership.objects.filter(user=self.operator, organization=self.org).update(is_active=False)
        done = set_checklist_status(actor=self.owner, item=item, done=True, note="Conferido pela gestão", expected_version=1)
        self.assertEqual(done.created_by_id, self.operator.pk)
        done.created_by = self.owner
        with self.assertRaises(ValidationError):
            done.save()
        comment.body = "Tentativa de alterar"
        with self.assertRaises(ValidationError):
            comment.save()
        with self.assertRaises(ValidationError):
            MatterComment.objects.filter(pk=comment.pk).update(body="Apagar histórico")

    def test_checklist_conference_and_reopen_require_evidence_and_concurrency_version(self):
        item = add_checklist(actor=self.owner, matter=self.matter, title="Conferir assinatura")
        with self.assertRaises(ValidationError):
            set_checklist_status(actor=self.owner, item=item, done=True, note="", expected_version=1)
        checked = set_checklist_status(actor=self.owner, item=item, done=True, note="Documento revisado", expected_version=1)
        self.assertTrue(checked.done)
        self.assertEqual(checked.version, 2)
        with self.assertRaises(ValidationError):
            set_checklist_status(actor=self.owner, item=item, done=False, note="Revisão", expected_version=1)
        reopened = set_checklist_status(actor=self.owner, item=item, done=False, note="Novo documento recebido", expected_version=2)
        self.assertFalse(reopened.done)
        self.assertIsNone(reopened.completed_by)
        self.assertTrue(AuditEvent.objects.filter(action="routine.check_done", description__contains="Documento revisado").exists())
        self.assertTrue(AuditEvent.objects.filter(action="routine.check_reopened", description__contains="Novo documento recebido").exists())

    def test_examples_idempotent_and_available_only_for_configured_niches(self):
        one = import_example(actor=self.owner, organization=self.org, key="acolhimento")
        two = import_example(actor=self.owner, organization=self.org, key="acolhimento")
        self.assertEqual(one.pk, two.pk)
        with self.assertRaises(ValidationError):
            import_example(actor=self.owner, organization=self.org, key="trabalhista")
        self.assertEqual(RoutineTemplate.objects.count(), 1)

    def test_form_preview_is_read_only_and_confirm_persists_then_redirects(self):
        template = self.template()
        self.client.force_login(self.owner)
        url = reverse("routines:detail", args=[template.pk])
        self.assertContains(self.client.get(url), "Revisar aplicação")
        payload = {"matter": self.matter.pk, "task_due_date": self.today.isoformat(), "expected_version": 1, "action": "preview"}
        self.assertContains(self.client.post(url, payload), "Confirmar aplicação")
        self.assertFalse(Task.objects.exists())
        self.assertRedirects(self.client.post(url, {**payload, "action": "apply"}), reverse("routines:matter", args=[self.matter.pk]))
        self.assertEqual(Task.objects.count(), 2)
        self.assertContains(self.client.get(reverse("routines:matter", args=[self.matter.pk])), "Comprovante de endereço")

    def test_csrf_get_and_comment_xss_escaping(self):
        template = self.template()
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        self.assertEqual(browser.get(reverse("routines:import", args=["acolhimento"])).status_code, 405)
        self.assertEqual(browser.post(reverse("routines:import", args=["acolhimento"])).status_code, 403)
        self.assertEqual(RoutineTemplate.objects.count(), 1)
        self.client.force_login(self.owner)
        url = reverse("routines:matter", args=[self.matter.pk])
        self.assertRedirects(self.client.post(url, {"action": "comment", "comment-body": "<script>alert(1)</script>"}), url)
        response = self.client.get(url)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_template_form_validates_niches_empty_steps_duplicate_and_limits(self):
        for changes in [{"niches": ["criminal"]}, {"tasks": [], "checklist": [], "documents": []},
            {"tasks": ["Duplicada", "duplicada"]}, {"documents": ["x" * 241]}, {"checklist": [str(i) for i in range(41)]}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.template(**changes)
        self.assertFalse(RoutineTemplate.objects.exists())

    def test_inactive_template_not_available_to_operator_but_snapshot_readable(self):
        template = self.template()
        self.apply(template)
        save_template(actor=self.owner, organization=self.org, template_id=template.pk, expected_version=1,
            data={**self.data, "is_active": False})
        self.assertFalse(visible_templates(self.operator, self.org).exists())
        self.client.force_login(self.operator)
        self.assertContains(self.client.get(reverse("routines:matter", args=[self.matter.pk])), "Rotina civil")

    def test_form_create_edit_add_check_and_conference_full_flow(self):
        self.client.force_login(self.owner)
        data = {**self.data, "tasks": "Revisar documentos\nPreparar retorno", "checklist": "Conferir cadastro", "documents": "Comprovante de endereço", "expected_version": ""}
        response = self.client.post(reverse("routines:create"), data)
        template = RoutineTemplate.objects.get()
        self.assertRedirects(response, reverse("routines:detail", args=[template.pk]))
        self.assertContains(self.client.get(reverse("routines:edit", args=[template.pk])), "Editar rotina")
        url = reverse("routines:matter", args=[self.matter.pk])
        self.assertRedirects(self.client.post(url, {"action": "check", "check-title": "Conferir protocolo", "check-kind": "check"}), url)
        item = MatterChecklist.objects.get()
        check_url = reverse("routines:check", args=[item.pk])
        self.assertEqual(self.client.get(check_url).status_code, 200)
        self.assertRedirects(self.client.post(check_url, {"done": "1", "note": "Protocolo recebido", "expected_version": "1"}), url)
        item.refresh_from_db()
        self.assertTrue(item.done)


@override_settings(**TEST_SETTINGS)
class SectorTutorialTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Escritório Teste", slug="org-tutorial-test", business_type="office")
        self.owner = User.objects.create_user("dona@tutorial.test", "TestPass123456!")
        self.operator = User.objects.create_user("operador@tutorial.test", "TestPass123456!")
        Membership.objects.create(organization=self.org, user=self.owner, role="owner")
        Membership.objects.create(organization=self.org, user=self.operator, role="operator")
        OrganizationSubscription.objects.create(organization=self.org, plan="max", status="active")

    def test_youtube_video_embed_and_thumbnail_calculation(self):
        from apps.routines.models import SectorTutorial
        tut = SectorTutorial.objects.create(
            organization=self.org,
            title="Como dar entrada no INSS",
            sector=SectorTutorial.Sector.PREVIDENCIARIO,
            description="Passo 1, 2, 3...",
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            created_by=self.owner,
        )
        self.assertEqual(tut.video_embed_url, "https://www.youtube.com/embed/dQw4w9WgXcQ?rel=0")
        self.assertEqual(tut.thumbnail_url, "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg")

        # Test short format youtu.be
        tut2 = SectorTutorial.objects.create(
            organization=self.org,
            title="Exigência INSS",
            sector=SectorTutorial.Sector.PREVIDENCIARIO,
            description="Passo 1, 2, 3...",
            video_url="https://youtu.be/dQw4w9WgXcQ",
            created_by=self.owner,
        )
        self.assertEqual(tut2.video_embed_url, "https://www.youtube.com/embed/dQw4w9WgXcQ?rel=0")

    def test_employee_can_watch_tutorial_but_cannot_create_or_delete(self):
        from apps.routines.models import SectorTutorial
        tut = SectorTutorial.objects.create(
            organization=self.org,
            title="Tutorial Previdenciário",
            sector=SectorTutorial.Sector.PREVIDENCIARIO,
            description="Instruções completas do procedimento",
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            created_by=self.owner,
        )

        client = Client()
        client.force_login(self.operator)

        # Employee can view tutorial list and watch the video in iframe
        res_list = client.get(reverse("routines:list"))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, "Tutorial Previdenciário")

        res_detail = client.get(reverse("routines:tutorial_detail", args=[tut.pk]))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "https://www.youtube.com/embed/dQw4w9WgXcQ?rel=0")

        # Employee CANNOT access create or delete (Forbidden 403)
        res_create = client.get(reverse("routines:tutorial_create"))
        self.assertEqual(res_create.status_code, 403)

        res_delete = client.post(reverse("routines:tutorial_delete", args=[tut.pk]))
        self.assertEqual(res_delete.status_code, 403)

    def test_admin_can_create_edit_and_delete_tutorial(self):
        from apps.routines.models import SectorTutorial
        client = Client()
        client.force_login(self.owner)

        # Admin creates tutorial
        data = {
            "sector": SectorTutorial.Sector.PREVIDENCIARIO,
            "title": "Tutorial Admin",
            "description": "Orientações operacionais para os funcionários",
            "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "order": 1,
            "is_published": True,
        }
        res = client.post(reverse("routines:tutorial_create"), data)
        tut = SectorTutorial.objects.get(title="Tutorial Admin")
        self.assertRedirects(res, reverse("routines:tutorial_detail", args=[tut.pk]))

        # Admin deletes tutorial
        res_del = client.post(reverse("routines:tutorial_delete", args=[tut.pk]))
        self.assertRedirects(res_del, reverse("routines:list"))
        self.assertFalse(SectorTutorial.objects.filter(pk=tut.pk).exists())

