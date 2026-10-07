import hashlib
import io
import json
import tempfile
import uuid
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization
from apps.legal.models import (
    Appointment, AuditEvent, Contact, CourtCase, Deadline, DeadlineRevision,
    Document, DocumentVersion, FinanceEntry, Matter, Opportunity, Payment, Task,
)
from apps.legal.forms import FinanceEntryForm, TaskForm
from apps.legal.services import add_document_version, audit, complete_task, confirm_deadline, record_payment


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class WorkspaceViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Escritório Alfa", slug="alfa-views", business_type="office")
        cls.other_org = Organization.objects.create(name="Escritório Beta", slug="beta-views", business_type="office")
        cls.owner = get_user_model().objects.create_user(email="owner-views@example.test", password="test-only-password")
        cls.manager = get_user_model().objects.create_user(email="manager-views@example.test", password="test-only-password")
        cls.operator = get_user_model().objects.create_user(email="operator-views@example.test", password="test-only-password")
        cls.viewer = get_user_model().objects.create_user(email="viewer-views@example.test", password="test-only-password")
        cls.outsider = get_user_model().objects.create_user(email="outsider-views@example.test", password="test-only-password")
        for user, role in [(cls.owner, "owner"), (cls.manager, "manager"), (cls.operator, "operator"), (cls.viewer, "viewer")]:
            Membership.objects.create(organization=cls.org, user=user, role=role)
        Membership.objects.create(organization=cls.other_org, user=cls.outsider, role="owner")
        cls.contact = Contact.objects.create(organization=cls.org, name="Pessoa permitida")
        cls.other_contact = Contact.objects.create(organization=cls.other_org, name="Pessoa de outro escritório")
        cls.matter = Matter.objects.create(organization=cls.org, title="Consultoria acessível", owner=cls.owner, client=cls.contact)
        cls.secret = Matter.objects.create(organization=cls.org, title="Conteúdo sigiloso exclusivo", owner=cls.owner, confidential=True)
        cls.other_matter = Matter.objects.create(organization=cls.other_org, title="Pasta exclusiva de Beta", owner=cls.outsider)
        cls.task = Task.objects.create(organization=cls.org, matter=cls.matter, title="Preparar peça", owner=cls.owner, due_date=date(2026, 10, 20))
        cls.deadline = Deadline.objects.create(organization=cls.org, matter=cls.matter, title="Protocolar peça", owner=cls.owner, due_date=date(2026, 10, 22), source="Publicação informada e identificada")
        cls.entry = FinanceEntry.objects.create(organization=cls.org, matter=cls.matter, description="Honorários de consultoria", amount=Decimal("1000.00"), due_date=date(2026, 10, 20))

    def setUp(self):
        self.private_directory = tempfile.TemporaryDirectory()
        self.media_override = override_settings(PRIVATE_MEDIA_ROOT=self.private_directory.name)
        self.media_override.enable()
        self.addCleanup(self.private_directory.cleanup)
        self.addCleanup(self.media_override.disable)
        self.client.force_login(self.owner)

    def make_document(self, matter=None, actor=None, content=b"conteudo autorizado"):
        matter = matter or self.matter
        actor = actor or self.owner
        document = Document.objects.create(organization=matter.organization, matter=matter, title="Documento privado", kind="Contrato", created_by=actor)
        version = add_document_version(document=document, actor=actor, file=SimpleUploadedFile("comprovante.txt", content, content_type="text/plain"))
        return document, version

    def response_bytes(self, response):
        # Django's test client closes the response when its iterator is
        # exhausted. Closing it twice emits request_finished outside that
        # wrapper and closes PostgreSQL's enclosing TestCase transaction.
        return b"".join(response.streaming_content)

    def test_anonymous_cannot_access_workspace_download_or_export(self):
        self.client.logout()
        for url in [reverse("legal:dashboard"), reverse("legal:list", args=["contacts"]), reverse("legal:export"), reverse("legal:document_download", args=[999])]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("core:login")))

    def test_pages_render_with_real_records(self):
        now = timezone.now()
        Appointment.objects.create(organization=self.org, matter=self.matter, title="Reunião", starts_at=now, ends_at=now + timedelta(hours=1), owner=self.owner)
        CourtCase.objects.create(organization=self.org, matter=self.matter, number="Administrativo 123", court="Órgão de teste")
        Opportunity.objects.create(organization=self.org, contact=self.contact, title="Oportunidade real", owner=self.owner)
        self.make_document()
        for module in ["matters", "contacts", "cases", "tasks", "deadlines", "appointments", "documents", "finance", "crm"]:
            with self.subTest(module=module):
                self.assertEqual(self.client.get(reverse("legal:list", args=[module])).status_code, 200)
                self.assertEqual(self.client.get(reverse("legal:create", args=[module])).status_code, 200)
        self.assertEqual(self.client.get(reverse("legal:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("legal:detail", args=[self.matter.pk])).status_code, 200)

    def test_cross_tenant_records_never_appear_or_open(self):
        response = self.client.get(reverse("legal:list", args=["matters"]), {"q": "Beta"})
        self.assertNotContains(response, self.other_matter.title)
        self.assertEqual(self.client.get(reverse("legal:detail", args=[self.other_matter.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("legal:edit", args=["contacts", self.other_contact.pk])).status_code, 404)

    def test_foreign_relationship_rejected_during_creation(self):
        response = self.client.post(reverse("legal:create", args=["matters"]), {
            "title": "Tentativa cruzada", "client": self.other_contact.pk, "nature": "advisory", "status": "active", "owner": self.owner.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("client", response.context["form"].errors)
        self.assertFalse(Matter.objects.filter(title="Tentativa cruzada").exists())

    def test_consultative_matter_created_without_court_case(self):
        response = self.client.post(reverse("legal:create", args=["matters"]), {
            "title": "Consultoria sem processo", "client": self.contact.pk, "nature": "advisory", "status": "active", "owner": self.owner.pk,
        })
        self.assertEqual(response.status_code, 302)
        matter = Matter.objects.get(title="Consultoria sem processo")
        self.assertEqual(matter.organization, self.org)
        self.assertEqual(matter.client, self.contact)
        self.assertFalse(matter.court_cases.exists())
        self.assertTrue(AuditEvent.objects.filter(object_type="legal.matter", object_id=str(matter.pk), action="record.created").exists())

    def test_confidentiality_applies_to_lists_dashboard_audit_and_forms(self):
        Task.objects.create(organization=self.org, matter=self.secret, title="Tarefa invisível", owner=self.owner, due_date=date(2026, 10, 20))
        audit(organization=self.org, actor=self.owner, action="record.created", obj=self.secret, description="Auditoria confidencial invisível")
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("legal:detail", args=[self.secret.pk])).status_code, 404)
        for url in [reverse("legal:list", args=["matters"]), reverse("legal:list", args=["tasks"]), reverse("legal:dashboard")]:
            response = self.client.get(url)
            self.assertNotContains(response, "Conteúdo sigiloso exclusivo")
            self.assertNotContains(response, "Tarefa invisível")
            self.assertNotContains(response, "Auditoria confidencial invisível")
        response = self.client.get(reverse("legal:create", args=["tasks"]))
        self.assertNotIn(self.secret, response.context["form"].fields["matter"].queryset)

    def test_viewer_can_read_but_cannot_mutate(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("legal:list", args=["tasks"])).status_code, 200)
        for url in [reverse("legal:create", args=["contacts"]), reverse("legal:edit", args=["tasks", self.task.pk]), reverse("legal:action", args=["tasks", self.task.pk, "complete"])]:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {"evidence": "Tentativa"}).status_code, 403)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)

    def test_operator_cannot_alter_confidentiality_or_access_members(self):
        self.secret.members.add(self.operator)
        self.client.force_login(self.operator)
        response = self.client.post(reverse("legal:edit", args=["matters", self.secret.pk]), {
            "title": self.secret.title, "nature": "advisory", "status": "active", "confidential": "", "owner": self.operator.pk, "members": [self.viewer.pk],
        })
        self.assertEqual(response.status_code, 302)
        self.secret.refresh_from_db()
        self.assertTrue(self.secret.confidential)
        self.assertEqual(self.secret.owner, self.owner)
        self.assertFalse(self.secret.members.filter(pk=self.viewer.pk).exists())

    def test_operator_cannot_access_finance_or_include_it_in_export(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse("legal:list", args=["finance"])).status_code, 403)
        self.assertEqual(self.client.post(reverse("legal:action", args=["finance", self.entry.pk, "payment"]), {"amount": "350.00", "date": "2026-10-07", "note": "Teste"}).status_code, 403)
        payload = self.response_bytes(self.client.get(reverse("legal:export")))
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            records = json.loads(archive.read("records.json"))
            self.assertNotIn("financeentry", records)
            self.assertNotIn("payment", records)

    def test_task_completion_does_not_fulfill_deadline(self):
        url = reverse("legal:action", args=["tasks", self.task.pk, "complete"])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)
        self.assertEqual(self.client.post(url, {"evidence": "Minuta revisada e anexada à pasta."}).status_code, 302)
        self.task.refresh_from_db()
        self.deadline.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)
        self.assertEqual(self.deadline.status, Deadline.Status.PENDING)

    def test_edit_preserves_task_completed_after_form_validation(self):
        original_validation = TaskForm.is_valid

        def validation_with_concurrent_completion(form):
            result = original_validation(form)
            complete_task(task=self.task, actor=self.owner, evidence="Entregue por outra sessão durante a edição.")
            return result

        with patch.object(TaskForm, "is_valid", validation_with_concurrent_completion):
            response = self.client.post(reverse("legal:edit", args=["tasks", self.task.pk]), {
                "matter": self.matter.pk, "title": "Título atualizado", "owner": self.owner.pk, "due_date": "2026-10-20", "priority": "normal",
            })
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Título atualizado")
        self.assertEqual(self.task.status, Task.Status.DONE)
        self.assertIn("outra sessão", self.task.completion_note)

    def test_financial_edit_rechecks_payments_after_form_validation(self):
        original_validation = FinanceEntryForm.is_valid

        def validation_with_concurrent_payment(form):
            result = original_validation(form)
            record_payment(entry=self.entry, actor=self.owner, amount=Decimal("950.00"), note="Baixa em outra sessão.")
            return result

        with patch.object(FinanceEntryForm, "is_valid", validation_with_concurrent_payment):
            response = self.client.post(reverse("legal:edit", args=["finance", self.entry.pk]), {
                "matter": self.matter.pk, "description": self.entry.description, "kind": "income", "amount": "900.00", "due_date": "2026-10-20",
            })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount, Decimal("1000.00"))
        self.assertEqual(self.entry.balance, Decimal("50.00"))

    def test_deadline_revision_requires_reason_and_new_confirmation(self):
        confirm_deadline(deadline=self.deadline, actor=self.owner)
        data = {"matter": self.matter.pk, "title": self.deadline.title, "source": self.deadline.source, "due_date": "2026-10-23", "owner": self.owner.pk}
        url = reverse("legal:edit", args=["deadlines", self.deadline.pk])
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("change_reason", response.context["form"].errors)
        self.deadline.refresh_from_db()
        self.assertEqual(self.deadline.due_date, date(2026, 10, 22))
        response = self.client.post(url, {**data, "change_reason": "Correção da data informada após conferência da fonte."})
        self.assertEqual(response.status_code, 302)
        self.deadline.refresh_from_db()
        self.assertEqual(self.deadline.due_date, date(2026, 10, 23))
        self.assertEqual(self.deadline.status, Deadline.Status.PENDING)
        revision = DeadlineRevision.objects.get(deadline=self.deadline)
        self.assertEqual(revision.previous_date, date(2026, 10, 22))

    def test_generic_deadline_form_cannot_forge_confirmation(self):
        response = self.client.post(reverse("legal:create", args=["deadlines"]), {
            "matter": self.matter.pk, "title": "Novo prazo", "source": "Fonte manual", "due_date": "2026-10-25", "owner": self.owner.pk,
            "status": "fulfilled", "confirmed_by": self.owner.pk, "evidence": "forjado",
        })
        self.assertEqual(response.status_code, 302)
        deadline = Deadline.objects.get(title="Novo prazo")
        self.assertEqual(deadline.status, Deadline.Status.PENDING)
        self.assertIsNone(deadline.confirmed_by)
        self.assertEqual(deadline.evidence, "")

    def test_partial_payment_and_reversal_reconcile(self):
        response = self.client.post(reverse("legal:action", args=["finance", self.entry.pk, "payment"]), {"amount": "350.00", "date": "2026-10-07", "note": "Comprovante registrado", "operation_key": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.entry.balance, Decimal("650.00"))
        payment = self.entry.payments.get()
        response = self.client.post(reverse("legal:action", args=["finance", self.entry.pk, "reverse"]), {"payment": payment.pk, "reason": "Baixa registrada por engano"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.entry.balance, Decimal("1000.00"))
        self.assertEqual(self.entry.payments.count(), 2)

    def test_repeated_payment_submission_has_a_single_effect(self):
        url = reverse("legal:action", args=["finance", self.entry.pk, "payment"])
        operation_key = self.client.get(url).context["form"]["operation_key"].value()
        payload = {"amount": "350.00", "date": "2026-10-07", "note": "Comprovante registrado", "operation_key": str(operation_key)}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.entry.payments.count(), 1)
        self.assertEqual(self.entry.balance, Decimal("650.00"))

    def test_private_file_download_obeys_org_confidentiality_and_revocation(self):
        document, version = self.make_document(matter=self.secret)
        url = reverse("legal:document_download", args=[version.pk])
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.secret.members.add(self.manager)
        self.assertEqual(self.response_bytes(self.client.get(url)), b"conteudo autorizado")
        self.secret.members.remove(self.manager)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_document_creation_upload_and_error_are_atomic(self):
        url = reverse("legal:create", args=["documents"])
        response = self.client.post(url, {"matter": self.matter.pk, "title": "Arquivo válido", "kind": "Comprovante", "file": SimpleUploadedFile("arquivo.txt", b"documento")})
        self.assertEqual(response.status_code, 302)
        document = Document.objects.get(title="Arquivo válido")
        self.assertEqual(document.versions.count(), 1)
        response = self.client.post(url, {"matter": self.matter.pk, "title": "Arquivo rejeitado", "kind": "Comprovante", "file": SimpleUploadedFile("arquivo.exe", b"invalido")})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Document.objects.filter(title="Arquivo rejeitado").exists())
        self.assertEqual(DocumentVersion.objects.count(), 1)

    def test_export_is_reconstructible_and_has_only_authorized_records(self):
        self.make_document()
        self.make_document(matter=self.secret, content=b"segredo fora do pacote")
        payment = record_payment(entry=self.entry, actor=self.owner, amount=Decimal("350.00"), note="Comprovante para exportação.")
        audit(organization=self.org, actor=self.owner, action="record.updated", obj=self.secret, description="Segredo fora da auditoria")
        self.client.force_login(self.manager)
        payload = self.response_bytes(self.client.get(reverse("legal:export")))
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            records = json.loads(archive.read("records.json"))
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual([item["id"] for item in records["matter"]], [self.matter.pk])
            self.assertEqual(len(records["documentversion"]), 1)
            self.assertEqual(records["payment"][0]["operation_key"], str(payment.operation_key))
            self.assertTrue(all(set(user) == {"id", "display_name"} for user in records["users"]))
            self.assertIn(self.owner.pk, [user["id"] for user in records["users"]])
            self.assertNotIn("segredo", archive.read("records.json").decode().lower())
            self.assertNotIn("password", archive.read("records.json").decode())
            for item in manifest["files"]:
                self.assertEqual(hashlib.sha256(archive.read(item["path"])).hexdigest(), item["sha256"])
        self.assertTrue(AuditEvent.objects.filter(actor=self.manager, action="workspace.exported").exists())

    def test_csrf_protects_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.post(reverse("legal:create", args=["contacts"]), {"name": "Sem CSRF", "kind": "person"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Contact.objects.filter(name="Sem CSRF").exists())

    def test_revoked_membership_cannot_access_former_records(self):
        Membership.objects.filter(user=self.owner, organization=self.org).update(is_active=False)
        self.assertEqual(self.client.get(reverse("legal:detail", args=[self.matter.pk])).status_code, 403)
