import hashlib
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import Membership, Organization
from apps.legal.models import (
    Appointment, AuditEvent, Contact, Deadline, Document, DocumentVersion,
    FinanceEntry, Matter, Opportunity, Payment, Task,
)
from apps.legal.services import (
    add_document_version, can_write, complete_task, confirm_deadline,
    fulfill_deadline, record_payment, reverse_payment, revise_deadline, visible_matters,
)


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class DomainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Escritório A", slug="escritorio-a")
        cls.other_org = Organization.objects.create(name="Escritório B", slug="escritorio-b")
        users = get_user_model().objects
        cls.owner = users.create_user(email="owner@example.test", password="test-only-password")
        cls.manager = users.create_user(email="manager@example.test", password="test-only-password")
        cls.viewer = users.create_user(email="viewer@example.test", password="test-only-password")
        cls.outsider = users.create_user(email="outsider@example.test", password="test-only-password")
        Membership.objects.create(organization=cls.org, user=cls.owner, role="owner", is_active=True)
        Membership.objects.create(organization=cls.org, user=cls.manager, role="manager", is_active=True)
        Membership.objects.create(organization=cls.org, user=cls.viewer, role="viewer", is_active=True)
        Membership.objects.create(organization=cls.other_org, user=cls.outsider, role="owner", is_active=True)
        cls.contact = Contact.objects.create(organization=cls.org, name="Cliente A")
        cls.other_contact = Contact.objects.create(organization=cls.other_org, name="Cliente B")
        cls.matter = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Consultoria")
        cls.secret = Matter.objects.create(organization=cls.org, owner=cls.owner, title="Sigilosa", confidential=True)
        cls.other_matter = Matter.objects.create(organization=cls.other_org, owner=cls.outsider, title="Pasta B")

    def make_deadline(self, **kwargs):
        values = dict(organization=self.org, matter=self.matter, owner=self.owner,
                      title="Protocolar manifestação", source="Publicação registrada manualmente",
                      due_date=date(2026, 10, 20))
        values.update(kwargs)
        return Deadline.objects.create(**values)

    def make_entry(self, **kwargs):
        values = dict(organization=self.org, matter=self.matter, description="Honorários",
                      amount=Decimal("1000.00"), due_date=date(2026, 10, 20))
        values.update(kwargs)
        return FinanceEntry.objects.create(**values)

    def test_cross_organization_foreign_keys_and_owners_are_rejected(self):
        with self.assertRaises(ValidationError):
            Matter.objects.create(organization=self.org, owner=self.owner, client=self.other_contact, title="Inválida")
        with self.assertRaises(ValidationError):
            self.make_deadline(matter=self.other_matter)
        with self.assertRaises(ValidationError):
            Task.objects.create(organization=self.org, owner=self.outsider, title="Inválida", due_date=date(2026, 10, 20))
        with self.assertRaises(ValidationError):
            self.matter.members.add(self.outsider)

    def test_records_cannot_be_moved_to_another_organization(self):
        self.contact.organization = self.other_org
        with self.assertRaises(ValidationError):
            self.contact.save()

    def test_existing_records_cannot_be_moved_out_of_confidential_matter(self):
        document = Document.objects.create(organization=self.org, matter=self.secret, title="Estratégia", created_by=self.owner)
        document.matter = self.matter
        with self.assertRaises(ValidationError):
            document.save()
        deadline = self.make_deadline(matter=self.secret)
        deadline.matter = self.matter
        with self.assertRaises(ValidationError):
            deadline.save()

    def test_confidential_matter_requires_explicit_access_even_for_manager(self):
        self.assertTrue(can_write(self.manager, self.org))
        self.assertFalse(visible_matters(self.manager, self.org).filter(pk=self.secret.pk).exists())
        self.assertFalse(visible_matters(self.outsider, self.org).exists())
        self.assertTrue(visible_matters(self.owner, self.org).filter(pk=self.secret.pk).exists())
        self.secret.members.add(self.manager)
        self.assertTrue(visible_matters(self.manager, self.org).filter(pk=self.secret.pk).exists())

    def test_restricted_matter_cannot_be_assigned_to_someone_without_access(self):
        with self.assertRaises(ValidationError):
            self.make_deadline(matter=self.secret, owner=self.manager)

    def test_suspended_organizations_do_not_allow_service_access(self):
        self.org.status = "suspended"
        self.org.save()
        self.assertFalse(can_write(self.owner, self.org))
        self.assertFalse(visible_matters(self.owner, self.org).exists())

    def test_read_only_and_inactive_members_cannot_write(self):
        task = Task.objects.create(organization=self.org, matter=self.matter, owner=self.owner,
                                   title="Preparar minuta", due_date=date(2026, 10, 20))
        with self.assertRaises(PermissionDenied):
            complete_task(task=task, actor=self.viewer, evidence="Minuta anexada")
        Membership.objects.filter(organization=self.org, user=self.manager).update(is_active=False)
        self.assertFalse(can_write(self.manager, self.org))
        self.assertFalse(visible_matters(self.manager, self.org).exists())

    def test_service_checks_confidential_access_independently_of_role(self):
        deadline = self.make_deadline(matter=self.secret)
        with self.assertRaises(PermissionDenied):
            confirm_deadline(deadline=deadline, actor=self.manager)
        with self.assertRaises(PermissionDenied):
            confirm_deadline(deadline=deadline, actor=self.outsider)
        deadline.refresh_from_db()
        self.assertEqual(deadline.status, Deadline.Status.PENDING)

    def test_task_completion_never_fulfills_deadline(self):
        deadline = confirm_deadline(deadline=self.make_deadline(), actor=self.owner)
        task = Task.objects.create(organization=self.org, matter=self.matter, owner=self.owner,
                                   title="Preparar minuta", due_date=deadline.due_date)
        with self.assertRaises(ValidationError):
            complete_task(task=task, actor=self.owner, evidence=" ")
        task = complete_task(task=task, actor=self.owner, evidence="Minuta revisada e anexada à pasta.")
        self.assertEqual(task.status, Task.Status.DONE)
        deadline.refresh_from_db()
        self.assertEqual(deadline.status, Deadline.Status.CONFIRMED)
        self.assertEqual(deadline.evidence, "")

    def test_recompletion_preserves_previous_evidence_in_audit(self):
        task = Task.objects.create(organization=self.org, matter=self.matter, owner=self.owner,
                                   title="Preparar minuta", due_date=date(2026, 10, 20))
        task = complete_task(task=task, actor=self.owner, evidence="Primeira entrega revisada.")
        task.status = Task.Status.TODO
        task.save(update_fields=["status"])
        complete_task(task=task, actor=self.owner, evidence="Segunda entrega após ajuste.")
        events = AuditEvent.objects.filter(action="task.completed", object_type="legal.task", object_id=str(task.pk))
        self.assertEqual(events.count(), 2)
        self.assertTrue(events.filter(description__contains="Primeira entrega revisada.").exists())
        self.assertTrue(events.filter(description__contains="Segunda entrega após ajuste.").exists())

    def test_deadline_revision_preserves_old_date_and_requires_reconfirmation(self):
        deadline = confirm_deadline(deadline=self.make_deadline(), actor=self.owner)
        with self.assertRaises(ValidationError):
            revise_deadline(deadline=deadline, actor=self.owner, due_date=date(2026, 10, 22), reason="")
        self.assertFalse(deadline.revisions.exists())
        revised = revise_deadline(deadline=deadline, actor=self.owner, due_date=date(2026, 10, 22), reason="Retificação da publicação.")
        revision = revised.revisions.get()
        self.assertEqual(revision.previous_date, date(2026, 10, 20))
        self.assertEqual(revision.new_date, date(2026, 10, 22))
        self.assertEqual(revision.actor, self.owner)
        self.assertEqual(revised.status, Deadline.Status.PENDING)
        self.assertIsNone(revised.confirmed_at)
        revised.due_date = date(2026, 10, 23)
        with self.assertRaises(ValidationError):
            revised.save()

    def test_fulfillment_requires_confirmation_and_evidence(self):
        deadline = self.make_deadline()
        with self.assertRaises(ValidationError):
            fulfill_deadline(deadline=deadline, actor=self.owner, evidence="Protocolo 123")
        deadline = confirm_deadline(deadline=deadline, actor=self.owner)
        with self.assertRaises(ValidationError):
            fulfill_deadline(deadline=deadline, actor=self.owner, evidence="")
        fulfilled = fulfill_deadline(deadline=deadline, actor=self.owner, evidence="Protocolo 123, comprovante conferido.")
        self.assertEqual(fulfilled.status, Deadline.Status.FULFILLED)
        self.assertEqual(fulfilled.confirmed_by, self.owner)
        self.assertTrue(AuditEvent.objects.filter(action="deadline.fulfilled", object_id=str(deadline.pk)).exists())

    def test_partial_payment_and_reversal_reconcile_without_deleting_history(self):
        entry = self.make_entry()
        payment = record_payment(entry=entry, actor=self.owner, amount=Decimal("350.00"))
        self.assertEqual(entry.paid_amount, Decimal("350.00"))
        self.assertEqual(entry.balance, Decimal("650.00"))
        reversal = reverse_payment(payment=payment, actor=self.owner, note="Baixa registrada por engano")
        self.assertEqual(reversal.reversal_of, payment)
        self.assertEqual(entry.balance, Decimal("1000.00"))
        self.assertEqual(entry.payments.count(), 2)
        with self.assertRaises(ValidationError):
            reverse_payment(payment=payment, actor=self.owner, note="Duplicado")
        with self.assertRaises(ValidationError):
            payment.delete()
        with self.assertRaises(ValidationError):
            Payment.objects.filter(pk=payment.pk).update(amount=Decimal("400.00"))
        replacement = Payment(pk=payment.pk, organization=self.org, entry=entry, created_by=self.owner,
                              amount=Decimal("1.00"), date=payment.date)
        with self.assertRaises(ValidationError):
            replacement.save()

    def test_overpayments_precision_and_wrong_tenant_are_rejected(self):
        entry = self.make_entry()
        record_payment(entry=entry, actor=self.owner, amount="350.00")
        for amount in ("650.01", "-1", "0", "1.001", "NaN", 0.1):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                record_payment(entry=entry, actor=self.owner, amount=amount)
        with self.assertRaises(PermissionDenied):
            record_payment(entry=entry, actor=self.outsider, amount="10.00")
        self.assertEqual(entry.payments.count(), 1)
        self.assertEqual(entry.balance, Decimal("650.00"))

    def test_payment_retry_reuses_operation_without_duplicate_movement_or_audit(self):
        entry = self.make_entry()
        key = uuid4()
        values = dict(entry=entry, actor=self.owner, amount="350.00", date=date(2026, 10, 20),
                      note="Comprovante 123", operation_key=key)
        first = record_payment(**values)
        retried = record_payment(**{**values, "operation_key": str(key)})
        self.assertEqual(first.pk, retried.pk)
        self.assertEqual(entry.payments.count(), 1)
        self.assertEqual(entry.balance, Decimal("650.00"))
        self.assertEqual(AuditEvent.objects.filter(action="payment.recorded").count(), 1)
        intentional = record_payment(**{**values, "operation_key": uuid4()})
        self.assertNotEqual(first.pk, intentional.pk)
        self.assertEqual(entry.payments.count(), 2)
        self.assertEqual(entry.balance, Decimal("300.00"))

    def test_payment_retry_rejects_changed_payload_and_actor(self):
        entry = self.make_entry()
        values = dict(entry=entry, actor=self.owner, amount="350.00", date=date(2026, 10, 20),
                      note="Comprovante 123", operation_key=uuid4())
        record_payment(**values)
        changes = [{"amount": "351.00"}, {"date": date(2026, 10, 21)}, {"note": "Outro comprovante"},
                   {"actor": self.manager}, {"entry": self.make_entry(description="Outro lançamento")}]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(ValidationError):
                record_payment(**{**values, **changed})
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(entry.balance, Decimal("650.00"))

    def test_payment_retry_after_full_payment_or_reversal_does_not_reapply(self):
        entry = self.make_entry()
        values = dict(entry=entry, actor=self.owner, amount="1000.00", date=date(2026, 10, 20),
                      note="Quitação", operation_key=uuid4())
        original = record_payment(**values)
        self.assertEqual(record_payment(**values).pk, original.pk)
        self.assertEqual(entry.balance, Decimal("0.00"))
        reverse_payment(payment=original, actor=self.owner, note="Correção")
        self.assertEqual(record_payment(**values).pk, original.pk)
        self.assertEqual(entry.balance, Decimal("1000.00"))
        self.assertEqual(entry.payments.count(), 2)

    def test_operator_cannot_record_financial_movements(self):
        Membership.objects.filter(organization=self.org, user=self.manager).update(role="operator")
        entry = self.make_entry()
        payment = record_payment(entry=entry, actor=self.owner, amount="350.00")
        with self.assertRaises(PermissionDenied):
            record_payment(entry=entry, actor=self.manager, amount="50.00")
        with self.assertRaises(PermissionDenied):
            reverse_payment(payment=payment, actor=self.manager, note="Teste")
        self.assertEqual(entry.balance, Decimal("650.00"))

    def test_revoked_historical_author_does_not_block_document_maintenance(self):
        document = Document.objects.create(organization=self.org, matter=self.matter, title="Contrato", created_by=self.manager)
        Membership.objects.filter(organization=self.org, user=self.manager).update(is_active=False)
        document.title = "Contrato revisado"
        document.save()
        self.assertEqual(document.created_by, self.manager)
        with self.assertRaises(ValidationError):
            Document.objects.create(organization=self.org, matter=self.matter, title="Novo", created_by=self.manager)

    def test_revoked_reviewer_preserves_confirmation_history(self):
        deadline = confirm_deadline(deadline=self.make_deadline(), actor=self.manager)
        Membership.objects.filter(organization=self.org, user=self.manager).update(is_active=False)
        deadline = fulfill_deadline(deadline=deadline, actor=self.owner, evidence="Protocolo conferido")
        self.assertEqual(deadline.confirmed_by, self.manager)
        self.assertEqual(deadline.status, Deadline.Status.FULFILLED)

    def test_client_funds_remain_distinct_from_office_income(self):
        client_fund = self.make_entry(kind=FinanceEntry.Kind.CLIENT_FUND, amount=Decimal("10000.00"))
        record_payment(entry=client_fund, actor=self.owner, amount="10000.00")
        self.assertTrue(client_fund.is_paid)
        self.assertFalse(FinanceEntry.objects.filter(kind=FinanceEntry.Kind.INCOME).exists())
        client_fund.kind = FinanceEntry.Kind.INCOME
        with self.assertRaises(ValidationError):
            client_fund.save()

    def test_documents_have_private_preserved_versions_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(PRIVATE_MEDIA_ROOT=directory):
            document = Document.objects.create(organization=self.org, matter=self.matter, title="Contrato", created_by=self.owner)
            first = add_document_version(document=document, actor=self.owner, file=SimpleUploadedFile("contrato.txt", b"primeira versao"))
            second = add_document_version(document=document, actor=self.owner, file=SimpleUploadedFile("contrato.txt", b"segunda versao"))
            self.assertEqual((first.number, second.number), (1, 2))
            self.assertNotEqual(first.file.name, second.file.name)
            self.assertEqual(first.checksum, hashlib.sha256(b"primeira versao").hexdigest())
            self.assertEqual(first.original_name, "contrato.txt")
            with first.file.open("rb") as stream:
                self.assertEqual(stream.read(), b"primeira versao")
            with self.assertRaises(ValueError):
                _ = first.file.url
            with self.assertRaises(ValidationError):
                first.save()
            with self.assertRaises(ValidationError):
                DocumentVersion.objects.filter(pk=first.pk).delete()
            with self.assertRaises(ValidationError):
                add_document_version(document=document, actor=self.owner, file=SimpleUploadedFile("script.html", b"<script>bad()</script>"))

    def test_document_upload_is_denied_without_confidential_access(self):
        document = Document.objects.create(organization=self.org, matter=self.secret, title="Estratégia", created_by=self.owner)
        with self.assertRaises(PermissionDenied):
            add_document_version(document=document, actor=self.manager, file=SimpleUploadedFile("segredo.txt", b"conteudo"))
        self.assertFalse(document.versions.exists())

    def test_appointment_and_lost_opportunity_have_domain_validation(self):
        start = timezone.now()
        with self.assertRaises(ValidationError):
            Appointment.objects.create(organization=self.org, owner=self.owner, title="Audiência",
                                       starts_at=start, ends_at=start - timedelta(minutes=30))
        with self.assertRaises(ValidationError):
            Opportunity.objects.create(organization=self.org, contact=self.contact, owner=self.owner,
                                       title="Consultoria", stage=Opportunity.Stage.LOST)
