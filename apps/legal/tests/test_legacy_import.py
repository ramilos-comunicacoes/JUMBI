import io
import json
import zipfile
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Membership, Organization, User
from apps.legal.models import (
    Appointment, AuditEvent, Contact, CourtCase, Deadline, FinanceEntry, LegacyImportRecord, Matter, Payment, Task,
)
from apps.legal.services import record_payment, reverse_payment, visible_matters
from apps.office.models import (
    Client, LegalCase, LegalDocument, OfficeFinanceEntry, OfficePurchase, StaffMember, WorkItem,
)


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class LegacyOfficeImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Jurídico", slug="juridico", business_type="office")
        cls.other = Organization.objects.create(name="Outro jurídico", slug="outro", business_type="office")
        cls.owner = User.objects.create_user(email="owner@legacy.example", password="test-password")
        cls.manager = User.objects.create_user(email="manager@legacy.example", password="test-password")
        cls.other_owner = User.objects.create_user(email="other@legacy.example", password="test-password")
        Membership.objects.create(organization=cls.org, user=cls.owner, role="owner")
        Membership.objects.create(organization=cls.org, user=cls.manager, role="manager")
        Membership.objects.create(organization=cls.other, user=cls.other_owner, role="owner")
        cls.source_client = Client.objects.create(organization=cls.org, name="Cliente legado", email="client@legacy.example")
        cls.source_staff = StaffMember.objects.create(organization=cls.org, name="Advogada", email=cls.owner.email, role="lawyer")
        cls.source_case = LegalCase.objects.create(
            organization=cls.org, client=cls.source_client, responsible=cls.source_staff,
            title="Caso confidencial", case_number="0001234-legado", confidential=True,
            description="Anotação original", custom_data={"protocolo": "ABC"},
            next_deadline=date(2026, 11, 2),
        )
        cls.source_task = WorkItem.objects.create(
            organization=cls.org, case=cls.source_case, client=cls.source_client,
            title="Entrega concluída", owner=cls.owner, status="done", due_date=date(2026, 10, 5),
        )
        cls.source_finance = OfficeFinanceEntry.objects.create(
            organization=cls.org, case=cls.source_case, client=cls.source_client,
            kind="revenue", description="Honorário anterior", amount=Decimal("425.00"),
            paid=True, due_date=date(2026, 10, 7),
        )
        cls.source_purchase = OfficePurchase.objects.create(
            organization=cls.org, supplier_name="Papelaria", item="Material", amount=Decimal("50.00"), paid=False,
        )

    def run_import(self, **kwargs):
        output = io.StringIO()
        options = dict(organization_id=[self.org.pk], stdout=output)
        options.update(kwargs)
        call_command("import_legacy_office", **options)
        return output.getvalue()

    def test_default_dry_run_validates_and_rolls_back(self):
        output = self.run_import()
        self.assertIn("SIMULAÇÃO", output)
        self.assertIn("Pendências de conferência", output)
        self.assertFalse(Contact.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(LegacyImportRecord.objects.exists())
        self.assertEqual(OfficeFinanceEntry.objects.get(pk=self.source_finance.pk).amount, Decimal("425.00"))

    def test_idempotency_preserves_every_target_and_source(self):
        self.run_import(apply=True)
        before = {model: list(model.objects.values_list("pk", flat=True)) for model in [
            Contact, Matter, CourtCase, Task, Deadline, FinanceEntry, Payment, LegacyImportRecord, AuditEvent,
        ]}
        output = self.run_import(apply=True)
        self.assertIn("já importados", output)
        for model, ids in before.items():
            self.assertEqual(list(model.objects.values_list("pk", flat=True)), ids)
        self.source_case.refresh_from_db()
        self.assertTrue(self.source_case.confidential)
        self.assertEqual(self.source_case.custom_data, {"protocolo": "ABC"})
        self.assertEqual(Contact.objects.count(), 2)  # Client and staff, no membership invented.
        self.assertEqual(Membership.objects.count(), 3)

    def test_confidential_access_and_pending_deadlines(self):
        WorkItem.objects.create(organization=self.org, case=self.source_case, kind="deadline", title="Prazo antigo cumprido",
                                due_date=date(2026, 10, 20), status="done", owner=self.manager)
        self.run_import(apply=True)
        matter = Matter.objects.get(title="Caso confidencial")
        self.assertTrue(matter.confidential)
        self.assertEqual(matter.owner, self.owner)
        self.assertFalse(matter.members.exists())
        self.assertFalse(visible_matters(self.manager, self.org).filter(pk=matter.pk).exists())
        self.assertEqual(Deadline.objects.count(), 2)
        for deadline in Deadline.objects.all():
            self.assertEqual(deadline.status, "pending")
            self.assertEqual(deadline.owner, self.owner)
            self.assertIsNone(deadline.confirmed_by)
            self.assertIsNone(deadline.confirmed_at)
            self.assertIn("conferência pendente", deadline.source)
        task = Task.objects.get(title="Entrega concluída")
        self.assertEqual(task.status, "done")
        self.assertIn("evidência anterior não informada", task.completion_note)

    def test_paid_balance_unknown_date_and_actor_are_preserved(self):
        self.run_import(apply=True, actor_email=self.manager.email)
        income = FinanceEntry.objects.get(kind="income")
        self.assertEqual(income.balance, Decimal("0.00"))
        payment = income.payments.get()
        self.assertTrue(payment.is_legacy_import)
        self.assertIsNone(payment.date)
        self.assertIsNone(payment.created_by)
        self.assertIn("sem comprovação documental", payment.note)
        record = LegacyImportRecord.objects.get(target_model="legal.payment", target_id=payment.pk)
        self.assertEqual(record.actor, self.manager)
        self.assertTrue(record.source_data["paid"])
        expense = FinanceEntry.objects.get(kind="expense")
        self.assertEqual(expense.balance, Decimal("50.00"))
        self.assertIn("Papelaria", expense.description)
        self.assertFalse(AuditEvent.objects.filter(actor__isnull=True).exists())

    def test_current_payment_still_requires_actor_date_and_import_can_be_reversed(self):
        self.run_import(apply=True)
        expense = FinanceEntry.objects.get(kind="expense")
        with self.assertRaises(ValidationError):
            Payment.objects.create(organization=self.org, entry=expense, amount="1.00", date=None, created_by=self.owner)
        with self.assertRaises(ValidationError):
            Payment.objects.create(organization=self.org, entry=expense, amount="1.00", date=date(2026, 10, 7), created_by=None)
        paid = record_payment(entry=expense, actor=self.owner, amount="5.00")
        self.assertIsNotNone(paid.date)
        self.assertEqual(paid.created_by, self.owner)
        self.assertFalse(paid.is_legacy_import)
        legacy = Payment.objects.get(is_legacy_import=True)
        reversal = reverse_payment(payment=legacy, actor=self.owner, note="Conciliação corrigiu marcação anterior")
        self.assertFalse(reversal.is_legacy_import)
        self.assertIsNotNone(reversal.date)
        self.assertEqual(legacy.entry.balance, Decimal("425.00"))

    def test_missing_dates_create_review_tasks_without_inventing_hearing_time(self):
        WorkItem.objects.create(organization=self.org, kind="hearing", title="Audiência sem horário", due_date=date(2026, 11, 5))
        WorkItem.objects.create(organization=self.org, kind="deadline", title="Prazo sem data")
        output = self.run_import(apply=True)
        self.assertFalse(Appointment.objects.exists())
        self.assertEqual(Deadline.objects.count(), 1)  # Only original next_deadline.
        hearing = Task.objects.get(title__contains="Audiência sem horário")
        self.assertEqual(hearing.due_date, date(2026, 11, 5))
        self.assertEqual(hearing.status, "todo")
        self.assertIn("nenhum horário foi presumido", hearing.description)
        self.assertIn("não prazo jurídico", Task.objects.get(title__contains="Prazo sem data").description)
        self.assertIn("data ausente", output)

    def test_selected_organization_isolation(self):
        Client.objects.create(organization=self.other, name="Pessoa fora do escopo")
        self.run_import(apply=True)
        self.assertFalse(Contact.objects.filter(organization=self.other).exists())
        self.assertFalse(Contact.objects.filter(name="Pessoa fora do escopo").exists())
        self.assertEqual(LegacyImportRecord.objects.exclude(organization=self.org).count(), 0)

    def test_source_cross_tenant_reference_aborts_everything(self):
        other_client = Client.objects.create(organization=self.other, name="Outro cliente")
        LegalCase.objects.filter(pk=self.source_case.pk).update(client=other_client)
        with self.assertRaisesMessage(CommandError, "entre organizações"):
            self.run_import(apply=True)
        self.assertFalse(Contact.objects.exists())

    def test_changed_source_is_not_silently_overwritten(self):
        self.run_import(apply=True)
        Client.objects.filter(pk=self.source_client.pk).update(name="Nome modificado depois")
        with self.assertRaisesMessage(CommandError, "origem mudou"):
            self.run_import(apply=True)
        self.assertTrue(Contact.objects.filter(name="Cliente legado").exists())

    def test_document_and_invalid_amount_abort_without_partial_import(self):
        doc = LegalDocument.objects.create(organization=self.org, title="Documento preservado", file="office/documents/a.pdf")
        with self.assertRaisesMessage(CommandError, "documentos legados"):
            self.run_import(apply=True)
        self.assertFalse(Contact.objects.exists())
        doc.delete()
        OfficePurchase.objects.filter(pk=self.source_purchase.pk).update(amount=Decimal("0.00"))
        with self.assertRaisesMessage(CommandError, "não positivo"):
            self.run_import(apply=True)
        self.assertFalse(Contact.objects.exists())

    def test_actor_must_be_real_active_manager_and_system_is_explicit(self):
        with self.assertRaisesMessage(CommandError, "não integra"):
            self.run_import(apply=True, actor_email=self.other_owner.email)
        self.run_import(apply=True)
        self.assertFalse(AuditEvent.objects.exclude(actor=None).exists())
        self.assertFalse(LegacyImportRecord.objects.exclude(actor=None).exists())

    def test_export_preserves_unknown_payment_fields_and_legacy_flag(self):
        self.run_import(apply=True)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("legal:export"))
        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        rows = json.loads(archive.read("records.json"))["payment"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["is_legacy_import"])
        self.assertIsNone(rows[0]["date"])
        self.assertIsNone(rows[0]["created_by_id"])
