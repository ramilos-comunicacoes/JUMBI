import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.billing.models import OrganizationSubscription
from apps.contracts.models import ContractRevision, ContractTemplate
from apps.core.models import Membership, Organization
from apps.core.management.commands.seed_workspace_showcase import MARKER, PHONE, PREFIX
from apps.legal.models import Appointment, AuditEvent, Contact, Deadline, DocumentVersion, Matter, Task
from apps.performance.models import Goal, GoalUpdate
from apps.performance.services import goal_progress, record_progress


@override_settings(DEBUG=False, JUMBI_ENFORCE_SUBSCRIPTIONS=True)
class WorkspaceShowcaseTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.media_override = override_settings(PRIVATE_MEDIA_ROOT=self.directory.name)
        self.media_override.enable()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.media_override.disable)
        self.org = Organization.objects.create(name="Demonstração", slug="jumbi-demonstracao", business_type="office")
        self.actor = get_user_model().objects.create_user(email="demo@jumbi.nabio.pro", password="testing-password-preserved")
        Membership.objects.create(organization=self.org, user=self.actor, role="manager")
        self.subscription = OrganizationSubscription.objects.create(organization=self.org, plan="max", status="demo")

    def test_seed_is_idempotent_preserves_user_progress_accounts_and_existing_records(self):
        previous_contact = Contact.objects.create(organization=self.org, name="Registro anterior preservado", phone="123")
        password_hash = self.actor.password
        call_command("seed_workspace_showcase", stdout=io.StringIO())
        self.assertEqual(Contact.objects.filter(organization=self.org, name__startswith=PREFIX, phone=PHONE).count(), 4)
        self.assertEqual(Matter.objects.filter(organization=self.org).count(), 4)
        self.assertEqual(Task.objects.filter(organization=self.org).count(), 4)
        self.assertEqual(set(Task.objects.values_list("status", flat=True)), {"todo", "doing", "done"})
        self.assertEqual(Deadline.objects.get().status, "pending")
        self.assertEqual(set(Appointment.objects.values_list("kind", flat=True)), {"hearing", "important_date"})
        self.assertEqual(Goal.objects.count(), 2)
        self.assertEqual(ContractTemplate.objects.count(), 1)
        self.assertEqual(ContractRevision.objects.count(), 1)
        self.assertEqual(DocumentVersion.objects.count(), 1)
        automatic = Goal.objects.get(metric="tasks")
        self.assertEqual(goal_progress(automatic, self.actor), 1)
        manual = Goal.objects.get(metric="manual")
        record_progress(actor=self.actor, organization=self.org, goal_id=manual.pk, value="7", note="Progresso do teste a preservar.")
        task = Task.objects.filter(status="todo").first()
        task.title = "Título editado pela pessoa de teste"
        task.save()
        snapshot = {model: model.objects.count() for model in [Contact, Matter, Task, Deadline, Appointment, Goal, GoalUpdate, ContractTemplate, ContractRevision, DocumentVersion, AuditEvent]}
        call_command("seed_workspace_showcase", stdout=io.StringIO())
        for model, count in snapshot.items():
            self.assertEqual(model.objects.count(), count)
        manual.refresh_from_db()
        task.refresh_from_db()
        previous_contact.refresh_from_db()
        self.actor.refresh_from_db()
        self.org.refresh_from_db()
        self.assertEqual(manual.manual_value, 7)
        self.assertEqual(task.title, "Título editado pela pessoa de teste")
        self.assertEqual(previous_contact.phone, "123")
        self.assertEqual(self.actor.password, password_hash)
        self.assertFalse(self.actor.is_staff)
        self.assertEqual(self.org.practice_areas, ["civil", "familia", "trabalhista", "previdenciario"])
        self.assertEqual(AuditEvent.objects.filter(action=MARKER).count(), 1)

    def test_refuses_non_demo_wrong_org_privileged_or_shared_accounts_without_writes(self):
        self.subscription.status = "active"
        self.subscription.save()
        with self.assertRaises(CommandError):
            call_command("seed_workspace_showcase", stdout=io.StringIO())
        self.subscription.status = "demo"
        self.subscription.save()
        with self.assertRaises(CommandError):
            call_command("seed_workspace_showcase", organization="outro-escritorio", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("seed_workspace_showcase", organization="jumbi-demonstracao-local", stdout=io.StringIO())
        self.actor.is_staff = True
        self.actor.save(update_fields=["is_staff"])
        with self.assertRaises(CommandError):
            call_command("seed_workspace_showcase", stdout=io.StringIO())
        self.actor.is_staff = False
        self.actor.save(update_fields=["is_staff"])
        other = Organization.objects.create(name="Outro", slug="outro-showcase", business_type="office")
        Membership.objects.create(organization=other, user=self.actor, role="manager")
        with self.assertRaises(CommandError):
            call_command("seed_workspace_showcase", stdout=io.StringIO())
        for model in [Contact, Matter, Task, Deadline, Appointment, Goal, ContractTemplate, ContractRevision, DocumentVersion, AuditEvent]:
            self.assertEqual(model.objects.count(), 0)
        self.org.refresh_from_db()
        self.assertEqual(self.org.practice_areas, [])
