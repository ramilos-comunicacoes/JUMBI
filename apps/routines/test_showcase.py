import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.billing.models import OrganizationSubscription
from apps.core.management.commands.seed_reuse_showcase import MARKER, PREVIOUS_MARKER, MATTER_TITLE, PREFIX
from apps.core.models import Membership, Organization, User
from apps.core.test_platform import TEST_SETTINGS
from apps.fees.models import FeeInstallment, FeePlan
from apps.legal.models import AuditEvent, Contact, Document, DocumentVersion, Matter, Payment, Task
from apps.legal.services import audit
from apps.portal.models import ClientAccess, DocumentReview, Publication, ReviewDecision
from apps.portal.services import visible_publications
from apps.routines.models import MatterChecklist, MatterComment, RoutineApplication


@override_settings(**TEST_SETTINGS)
class ReuseShowcaseTests(TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        self.media_settings = override_settings(PRIVATE_MEDIA_ROOT=self.storage.name, MEDIA_ROOT=self.storage.name)
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.org = Organization.objects.create(name="DEMONSTRAÇÃO", slug="jumbi-demonstracao-local", business_type="office", practice_areas=["civil"])
        self.owner = User.objects.create_user("demo@jumbi.local", "TestOwner!4578321", first_name="Conta", last_name="Demo")
        Membership.objects.create(organization=self.org, user=self.owner, role="owner")
        self.subscription = OrganizationSubscription.objects.create(organization=self.org, plan="max", status="demo")
        contact = Contact.objects.create(organization=self.org, name=PREFIX + "Ana — Civil",
            email="showcase-civil@example.invalid", document="FICTÍCIO-1")
        self.matter = Matter.objects.create(organization=self.org, title=MATTER_TITLE, client=contact,
            area="civil", owner=self.owner, description="Pessoa e atendimento inteiramente fictícios.")
        audit(organization=self.org, actor=self.owner, action=PREVIOUS_MARKER, description="Carga anterior fictícia de teste.")

    def execute(self, password="TestClient!9845267"):
        output = io.StringIO()
        with patch.dict(os.environ, {"JUMBI_DEMO_CLIENT_PASSWORD": password}):
            call_command("seed_reuse_showcase", organization=self.org.slug, stdout=output)
        return output.getvalue()

    def test_full_showcase_uses_independent_review_and_persists_real_scoped_records(self):
        original_password = self.owner.password
        result = self.execute()
        self.assertNotIn("TestClient!9845267", result)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.password, original_password)
        self.assertEqual(RoutineApplication.objects.count(), 1)
        self.assertEqual(Task.objects.count(), 3)
        self.assertEqual(MatterChecklist.objects.filter(done=True).count(), 1)
        self.assertEqual(MatterComment.objects.count(), 1)
        self.assertEqual(FeePlan.objects.get().total_amount, 1200)
        self.assertEqual(list(FeeInstallment.objects.values_list("amount", flat=True)), [400, 400, 400])
        self.assertFalse(Payment.objects.exists())
        helper = User.objects.get(email="colaborador.demo.v5@jumbi.local")
        client = User.objects.get(email="cliente.demo@jumbi.local")
        self.assertFalse(helper.has_usable_password())
        self.assertTrue(client.check_password("TestClient!9845267"))
        self.assertTrue(client.first_name.startswith("DEMONSTRAÇÃO"))
        review = DocumentReview.objects.get()
        self.assertEqual(review.requested_by_id, helper.pk)
        self.assertEqual(review.version.uploaded_by_id, helper.pk)
        self.assertEqual(review.reviewer_id, self.owner.pk)
        self.assertEqual(ReviewDecision.objects.get().outcome, "approved")
        self.assertEqual(visible_publications(client, self.org).count(), 1)
        self.assertEqual(ClientAccess.objects.get().contact_id, self.matter.client_id)
        self.assertTrue(AuditEvent.objects.filter(action=MARKER).exists())
        with DocumentVersion.objects.get().file.open("rb") as source:
            self.assertIn("INTEIRAMENTE FICTÍCIO", source.read().decode("utf-8"))

    def test_repeated_command_preserves_progress_credentials_and_existing_data(self):
        existing_task = Task.objects.create(organization=self.org, matter=self.matter, owner=self.owner,
            title="Tarefa anterior", due_date="2026-10-09")
        self.execute()
        client = User.objects.get(email="cliente.demo@jumbi.local")
        client.set_password("PasswordChangedByClient!839172")
        client.save(update_fields=["password"])
        password = client.password
        added_task = Task.objects.exclude(pk=existing_task.pk).first()
        added_task.status = "doing"
        added_task.save()
        counts = {model: model.objects.count() for model in [User, Membership, Task, Document, FeePlan, FeeInstallment, Publication, MatterChecklist, MatterComment]}
        self.execute(password="AnotherPassword!348274")
        client.refresh_from_db()
        added_task.refresh_from_db()
        existing_task.refresh_from_db()
        self.assertEqual(client.password, password)
        self.assertEqual(added_task.status, "doing")
        self.assertEqual(existing_task.title, "Tarefa anterior")
        self.assertEqual(counts, {model: model.objects.count() for model in counts})

    def test_existing_reserved_client_keeps_password_without_environment_value(self):
        client = User.objects.create_user("cliente.demo@jumbi.local", "KeepExistingClient!847263",
            first_name="DEMONSTRAÇÃO", last_name="Cliente do portal")
        Membership.objects.create(organization=self.org, user=client, role="client")
        password = client.password
        self.execute(password="")
        client.refresh_from_db()
        self.assertEqual(client.password, password)
        self.assertEqual(Publication.objects.count(), 1)

    def test_missing_password_and_cross_workspace_collision_roll_back_everything(self):
        with self.assertRaises(CommandError):
            self.execute(password="")
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(RoutineApplication.objects.exists())
        other = Organization.objects.create(name="Outro escritório", slug="other-showcase", business_type="office")
        occupied = User.objects.create_user("cliente.demo@jumbi.local", "OtherTenantOnly!943272",
            first_name="DEMONSTRAÇÃO", last_name="Cliente do portal")
        Membership.objects.create(organization=other, user=occupied, role="client")
        with self.assertRaises(CommandError):
            self.execute()
        self.assertFalse(User.objects.filter(email="colaborador.demo.v5@jumbi.local").exists())
        self.assertFalse(Publication.objects.exists())
        self.assertEqual(Membership.objects.filter(user=occupied, organization=other).count(), 1)

    def test_refuses_changed_fictional_identity_or_non_demo_subscription(self):
        self.subscription.status = "active"
        self.subscription.save()
        with self.assertRaises(CommandError):
            self.execute()
        self.subscription.status = "demo"
        self.subscription.save()
        self.matter.client.name = "Pessoa que não está identificada como demonstração"
        self.matter.client.save()
        with self.assertRaises(CommandError):
            self.execute()
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(FeePlan.objects.exists())

    def test_failure_after_upload_removes_only_new_file_and_rolls_back_seed(self):
        keep = Path(self.storage.name) / "arquivo-anterior.txt"
        keep.write_text("Arquivo anterior preservado", encoding="utf-8")
        with patch("apps.core.management.commands.seed_reuse_showcase.publish_version", side_effect=RuntimeError("Falha simulada")):
            with self.assertRaises(RuntimeError):
                self.execute()
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(DocumentVersion.objects.exists())
        self.assertFalse(RoutineApplication.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action=MARKER).exists())
        self.assertEqual([path for path in Path(self.storage.name).rglob("*") if path.is_file()], [keep])
