from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.http import Http404
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization
from apps.legal.models import Contact, Deadline, Matter, Task
from apps.notifications.models import Notification
from apps.notifications.services import change_state, generate_for_user, inbox_queryset, mark_all_read, present, unread_count, visible_notifications


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False, TIME_ZONE="America/Fortaleza")
class NotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = date(2027, 2, 28)
        cls.org = Organization.objects.create(name="Aurora", slug="notifications-aurora", business_type="office")
        cls.other = Organization.objects.create(name="Outro", slug="notifications-other", business_type="office")
        cls.owner = get_user_model().objects.create_user(email="notifications-owner@example.test", password="test-only-password")
        cls.viewer = get_user_model().objects.create_user(email="notifications-viewer@example.test", password="test-only-password")
        cls.outsider = get_user_model().objects.create_user(email="notifications-other@example.test", password="test-only-password")
        cls.portal_user = get_user_model().objects.create_user(email="notifications-portal@example.test", password="test-only-password")
        cls.owner_membership = Membership.objects.create(organization=cls.org, user=cls.owner, role="owner")
        cls.viewer_membership = Membership.objects.create(organization=cls.org, user=cls.viewer, role="viewer")
        Membership.objects.create(organization=cls.other, user=cls.outsider, role="owner")
        Membership.objects.create(organization=cls.org, user=cls.portal_user, role="client")
        cls.contact = Contact.objects.create(organization=cls.org, name="Ana & Silva", birth_date=date(1992, 2, 29), phone="88992745456")
        cls.matter = Matter.objects.create(organization=cls.org, title="Pasta acessível", owner=cls.owner, client=cls.contact)
        cls.secret = Matter.objects.create(organization=cls.org, title="Pasta restrita", owner=cls.owner, confidential=True)
        cls.other_matter = Matter.objects.create(organization=cls.other, title="Pasta externa", owner=cls.outsider)
        cls.task = Task.objects.create(organization=cls.org, matter=cls.matter, title="Revisar contrato", owner=cls.owner, due_date=cls.today + timedelta(days=2))
        cls.deadline = Deadline.objects.create(organization=cls.org, matter=cls.matter, title="Protocolar recurso", owner=cls.owner, due_date=cls.today - timedelta(days=2), source="Publicação conferida")
        cls.secret_task = Task.objects.create(organization=cls.org, matter=cls.secret, title="Entrega sigilosa", owner=cls.owner, due_date=cls.today)
        cls.other_task = Task.objects.create(organization=cls.other, matter=cls.other_matter, title="Tarefa externa", owner=cls.outsider, due_date=cls.today)

    def request(self, user=None):
        req = RequestFactory().get("/notificacoes/")
        req.user = user or self.viewer
        req.organization = self.org
        req.membership = self.owner_membership if req.user == self.owner else self.viewer_membership
        return req

    def generate(self, user=None, today=None):
        return generate_for_user(user or self.viewer, self.org, today=today or self.today)

    def test_generates_due_overdue_and_visible_birthday_once(self):
        self.assertEqual(self.generate(), 3)
        self.assertEqual(self.generate(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.viewer).count(), 3)
        self.assertFalse(Notification.objects.filter(recipient=self.viewer, task=self.secret_task).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.viewer, task=self.other_task).exists())

    def test_future_and_completed_records_are_not_generated(self):
        Task.objects.create(organization=self.org, title="Ainda longe", owner=self.owner, due_date=self.today + timedelta(days=4))
        Task.objects.create(organization=self.org, title="Já feita", owner=self.owner, due_date=self.today, status="done", completion_note="Entregue")
        self.generate()
        self.assertEqual(Notification.objects.filter(recipient=self.viewer, kind="task").count(), 1)

    def test_read_archive_choices_survive_regeneration_and_next_day(self):
        self.generate()
        note = Notification.objects.get(recipient=self.viewer, task=self.task)
        change_state(user=self.viewer, organization=self.org, pk=note.pk, action="read")
        change_state(user=self.viewer, organization=self.org, pk=note.pk, action="archive")
        self.generate(today=self.today + timedelta(days=1))
        note.refresh_from_db()
        self.assertIsNotNone(note.read_at)
        self.assertIsNotNone(note.dismissed_at)
        self.assertEqual(Notification.objects.filter(recipient=self.viewer, task=self.task).count(), 1)
        change_state(user=self.viewer, organization=self.org, pk=note.pk, action="restore")
        change_state(user=self.viewer, organization=self.org, pk=note.pk, action="unread")
        note.refresh_from_db()
        self.assertIsNone(note.read_at)
        self.assertIsNone(note.dismissed_at)

    def test_personal_state_does_not_change_another_recipient(self):
        self.generate()
        self.generate(self.owner)
        mark_all_read(user=self.viewer, organization=self.org)
        self.assertEqual(unread_count(self.request()), 0)
        self.assertEqual(unread_count(self.request(self.owner)), 4)

    def test_unread_badge_uses_a_constant_number_of_queries(self):
        self.generate()
        with self.assertNumQueries(3):
            self.assertEqual(unread_count(self.request()), 3)

    def test_new_due_date_is_a_new_occurrence_and_old_date_is_hidden(self):
        self.generate()
        original = Notification.objects.get(recipient=self.viewer, task=self.task)
        self.task.due_date = self.today
        self.task.save()
        self.generate()
        self.assertEqual(Notification.objects.filter(recipient=self.viewer, task=self.task).count(), 2)
        self.assertFalse(visible_notifications(self.viewer, self.org).filter(pk=original.pk).exists())
        self.assertEqual(visible_notifications(self.viewer, self.org).filter(task=self.task).count(), 1)

    def test_revoked_confidential_access_hides_existing_notice_and_forbids_action(self):
        self.secret.members.add(self.viewer)
        self.generate()
        note = Notification.objects.get(recipient=self.viewer, task=self.secret_task)
        self.secret.members.remove(self.viewer)
        self.assertFalse(visible_notifications(self.viewer, self.org).filter(pk=note.pk).exists())
        self.assertEqual(unread_count(self.request()), 3)
        with self.assertRaises(Http404):
            change_state(user=self.viewer, organization=self.org, pk=note.pk, action="read")

    def test_confidential_client_birthday_is_hidden_after_access_revocation(self):
        self.matter.confidential = True
        self.matter.save()
        self.matter.members.add(self.viewer)
        self.generate()
        birthday = Notification.objects.get(recipient=self.viewer, kind="birthday")
        self.matter.members.remove(self.viewer)
        self.assertFalse(visible_notifications(self.viewer, self.org).filter(pk=birthday.pk).exists())

    def test_revoked_membership_and_client_role_have_no_internal_notices(self):
        self.generate()
        self.viewer_membership.is_active = False
        self.viewer_membership.save()
        self.assertEqual(self.generate(), 0)
        self.assertEqual(unread_count(self.request()), 0)
        self.assertEqual(self.generate(self.portal_user), 0)
        self.assertFalse(visible_notifications(self.portal_user, self.org).exists())

    def test_other_office_and_other_recipient_cannot_change_notice(self):
        self.generate()
        note = Notification.objects.get(recipient=self.viewer, task=self.task)
        for user, org in [(self.owner, self.org), (self.outsider, self.other), (self.viewer, self.other)]:
            with self.subTest(user=user.email), self.assertRaises(Http404):
                change_state(user=user, organization=org, pk=note.pk, action="archive")

    def test_completed_task_is_resolved_and_not_in_unread_badge(self):
        self.generate()
        self.task.status = "done"
        self.task.completion_note = "Entregue ao cliente"
        self.task.save()
        self.assertEqual(unread_count(self.request()), 2)
        note = inbox_queryset(self.viewer, self.org).get(task=self.task)
        item = present(note, self.request(), today=self.today)
        self.assertTrue(item["resolved"])
        self.assertFalse(item["is_unread"])
        self.assertFalse(inbox_queryset(self.viewer, self.org, status="unread").filter(task=self.task).exists())

    def test_render_uses_current_title_and_safe_whatsapp_url(self):
        self.generate()
        self.task.title = "Título atualizado"
        self.task.save()
        note = inbox_queryset(self.viewer, self.org).get(task=self.task)
        self.assertEqual(present(note, self.request(), today=self.today)["title"], "Título atualizado")
        birthday = inbox_queryset(self.viewer, self.org).get(kind="birthday")
        item = present(birthday, self.request(), today=self.today)
        self.assertTrue(item["whatsapp_url"].startswith("https://wa.me/5588992745456?text="))
        self.assertIn("Ana+%26+Silva", item["whatsapp_url"])

    def test_birthday_has_one_annual_occurrence_including_february_29(self):
        self.generate()
        self.generate(today=date(2028, 2, 28))
        self.assertEqual(Notification.objects.filter(recipient=self.viewer, kind="birthday").count(), 1)
        self.generate(today=date(2028, 2, 29))
        self.assertEqual(Notification.objects.filter(recipient=self.viewer, kind="birthday").count(), 2)

    def test_changed_birthday_hides_stale_occurrence_and_rejects_its_actions(self):
        self.generate()
        note = Notification.objects.get(recipient=self.viewer, kind="birthday")
        self.contact.birth_date = date(1992, 3, 1)
        self.contact.save()
        self.assertFalse(visible_notifications(self.viewer, self.org).filter(pk=note.pk).exists())
        with self.assertRaises(Http404):
            change_state(user=self.viewer, organization=self.org, pk=note.pk, action="read")

    def test_historical_birthday_has_no_whatsapp_action(self):
        self.generate()
        note = inbox_queryset(self.viewer, self.org).get(kind="birthday")
        item = present(note, self.request(), today=self.today + timedelta(days=1))
        self.assertIsNone(item["whatsapp_url"])
        self.assertFalse(item["birthday_is_today"])
        self.assertEqual(item["status"], "Aniversário registrado")

    def test_cross_tenant_subject_fails_model_validation(self):
        with self.assertRaises(ValidationError):
            Notification.objects.create(organization=self.org, recipient=self.viewer, kind="task", task=self.other_task, source_date=self.today)
        with self.assertRaises(ValidationError):
            Notification.objects.create(organization=self.org, recipient=self.portal_user, kind="task", task=self.task, source_date=self.today)

    @override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
    def test_unavailable_subscription_generates_and_exposes_nothing(self):
        self.assertEqual(self.generate(), 0)
        self.assertFalse(visible_notifications(self.viewer, self.org).exists())

    def test_management_command_is_idempotent_and_skips_portal_clients(self):
        with patch("apps.notifications.services.timezone.localdate", return_value=self.today):
            call_command("generate_notifications", verbosity=0)
            count = Notification.objects.count()
            call_command("generate_notifications", verbosity=0)
        self.assertEqual(Notification.objects.count(), count)
        self.assertFalse(Notification.objects.filter(recipient=self.portal_user).exists())

    def test_inbox_read_archive_filter_flow_and_readonly_links(self):
        self.client.force_login(self.viewer)
        with patch("apps.notifications.services.timezone.localdate", return_value=self.today):
            response = self.client.get(reverse("notifications:inbox"))
        self.assertContains(response, "Notificações")
        self.assertContains(response, "Ana &amp; Silva")
        self.assertNotContains(response, "Entrega sigilosa")
        self.assertNotContains(response, reverse("legal:edit", args=["tasks", self.task.pk]))
        note = Notification.objects.get(recipient=self.viewer, task=self.task)
        route = reverse("notifications:state", args=[note.pk, "archive"])
        self.assertEqual(self.client.get(route).status_code, 405)
        self.assertEqual(self.client.post(route).status_code, 302)
        response = self.client.get(reverse("notifications:inbox"), {"status": "archived", "kind": "task"})
        self.assertContains(response, "Revisar contrato")
        self.assertContains(response, "Restaurar")

    def test_csrf_and_client_portal_routes_are_enforced(self):
        self.generate()
        note = Notification.objects.get(recipient=self.viewer, task=self.task)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.viewer)
        self.assertEqual(csrf_client.post(reverse("notifications:state", args=[note.pk, "read"])).status_code, 403)
        self.client.force_login(self.portal_user)
        self.assertEqual(self.client.get(reverse("notifications:inbox")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("notifications:inbox")).status_code, 302)

    def test_invalid_filters_are_safe_and_bulk_read_only_changes_visible_items(self):
        self.secret.members.add(self.viewer)
        self.generate()
        self.secret.members.remove(self.viewer)
        self.assertEqual(mark_all_read(user=self.viewer, organization=self.org), 3)
        self.assertIsNone(Notification.objects.get(recipient=self.viewer, task=self.secret_task).read_at)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("notifications:inbox"), {"status": "invalid", "kind": "invalid", "page": "nonsense"}).status_code, 200)
