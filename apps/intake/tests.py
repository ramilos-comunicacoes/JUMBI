import io
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization, User
from apps.core.test_platform import TEST_SETTINGS
from apps.legal.models import AuditEvent, Contact, CourtCase, Matter
from .models import ImportBatch
from .services import PreviewUnavailable, commit_import, parse_upload, stage_import, validate_rows


def upload(text, name="dados.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8-sig"), content_type="text/csv")


def xlsx(rows, *, extra_sheet=None):
    from openpyxl import Workbook
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    if extra_sheet:
        workbook.create_sheet("Outra").append(extra_sheet)
    output = io.BytesIO()
    workbook.save(output)
    return SimpleUploadedFile("dados.xlsx", output.getvalue())


@override_settings(**TEST_SETTINGS)
class ImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Importação", slug="import-test", business_type="office")
        cls.other_org = Organization.objects.create(name="Outro", slug="import-other", business_type="office")
        cls.owner = User.objects.create_user("owner@intake.test")
        cls.manager = User.objects.create_user("manager@intake.test")
        cls.operator = User.objects.create_user("operator@intake.test")
        cls.viewer = User.objects.create_user("viewer@intake.test")
        cls.client_user = User.objects.create_user("client@intake.test")
        cls.other = User.objects.create_user("other@intake.test")
        for user, role in [(cls.owner, "owner"), (cls.manager, "manager"), (cls.operator, "operator"), (cls.viewer, "viewer"), (cls.client_user, "client")]:
            Membership.objects.create(organization=cls.org, user=user, role=role)
        Membership.objects.create(organization=cls.other_org, user=cls.other, role="owner")
        cls.matter = Matter.objects.create(organization=cls.org, title="Pasta comum", owner=cls.owner)
        cls.secret = Matter.objects.create(organization=cls.org, title="Pasta sigilosa", owner=cls.owner, confidential=True)
        cls.other_matter = Matter.objects.create(organization=cls.other_org, title="Pasta externa", owner=cls.other)

    def stage(self, text="Nome;E-mail\nMaria Teste;maria@example.test\n", kind="contacts", actor=None):
        return stage_import(actor=actor or self.owner, organization=self.org, kind=kind, upload=upload(text))

    def commit(self, batch, actor=None):
        return commit_import(actor=actor or self.owner, organization=self.org, batch_id=batch.pk)

    def review(self, batch, actor=None):
        return validate_rows(actor=actor or self.owner, organization=self.org, kind=batch.kind, rows=batch.rows)[0]

    def test_upload_creates_only_private_preview_and_maps_accents_and_date(self):
        batch = self.stage("Nome;Tipo de pessoa;CPF / CNPJ;Nascimento;Telefone\nÁgata Lima;Pessoa física;012.345.678-90;20/01/1990;+55 88 99274-5456\n")
        self.assertEqual(Contact.objects.count(), 0)
        self.assertEqual(batch.rows[0]["data"]["birth_date"], "1990-01-20")
        self.assertEqual(batch.columns[0], {"source": "Nome", "field": "name", "label": "Nome"})
        self.assertEqual(batch.row_count, 1)
        self.assertTrue(self.review(batch)["can_confirm"])
        self.assertGreater(batch.expires_at, timezone.now() + timedelta(hours=23))

    def test_confirm_creates_audited_records_and_repeated_confirm_is_idempotent(self):
        batch = self.stage()
        committed, created = self.commit(batch)
        self.assertTrue(created)
        self.assertEqual(committed.created_count, 1)
        self.assertEqual(committed.rows, [])
        self.assertEqual(Contact.objects.filter(organization=self.org, name="Maria Teste").count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="record.imported").count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="workspace.imported").count(), 1)
        _, repeated = self.commit(batch)
        self.assertFalse(repeated)
        self.assertEqual(Contact.objects.count(), 1)

    def test_invalid_row_blocks_entire_batch(self):
        batch = self.stage("Nome;E-mail\nMaria;valid@example.test\nFulano;email-invalido\n")
        review = self.review(batch)
        self.assertEqual(review["valid_count"], 1)
        self.assertEqual(review["invalid_count"], 1)
        with self.assertRaises(ValidationError):
            self.commit(batch)
        self.assertFalse(Contact.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_existing_contact_or_duplicate_within_file_never_overwrites(self):
        Contact.objects.create(organization=self.org, name="Maria Teste", email="original@example.test", document="123.456.789-00")
        for text in ["Nome\nmaria teste\n", "Nome;CPF\nOutra Pessoa;12345678900\n", "Nome;E-mail\nOutra Pessoa;ORIGINAL@example.test\n", "Nome;E-mail\nUm;a@example.test\nDois;A@example.test\n"]:
            with self.subTest(text=text):
                batch = self.stage(text)
                self.assertFalse(self.review(batch)["can_confirm"])
                with self.assertRaises(ValidationError):
                    self.commit(batch)
        self.assertEqual(Contact.objects.count(), 1)
        self.assertEqual(Contact.objects.get().email, "original@example.test")

    def test_contacts_of_another_office_do_not_block_or_leak(self):
        Contact.objects.create(organization=self.other_org, name="Maria Teste", email="maria@example.test")
        self.commit(self.stage())
        self.assertEqual(Contact.objects.filter(organization=self.org).count(), 1)

    def test_duplicate_created_after_preview_is_detected_at_confirmation(self):
        batch = self.stage()
        self.assertTrue(self.review(batch)["can_confirm"])
        Contact.objects.create(organization=self.org, name="Outra pessoa", email="maria@example.test")
        with self.assertRaises(ValidationError):
            self.commit(batch)
        self.assertEqual(Contact.objects.count(), 1)

    def test_two_previews_with_same_rows_cannot_both_create_records(self):
        first, second = self.stage(), self.stage()
        self.commit(first)
        with self.assertRaises(ValidationError):
            self.commit(second)
        self.assertEqual(Contact.objects.count(), 1)

    def test_cases_link_only_accessible_existing_matter_without_creating_pasta(self):
        batch = self.stage(f"ID da pasta;Número do processo;Tribunal\n{self.matter.pk};0001234-56.2026.8.06.0001;TJCE\n", kind="cases", actor=self.manager)
        self.commit(batch, actor=self.manager)
        case = CourtCase.objects.get()
        self.assertEqual(case.matter, self.matter)
        self.assertEqual(case.number, "0001234-56.2026.8.06.0001")
        self.assertEqual(Matter.objects.count(), 3)

    def test_confidential_and_other_office_cases_rejected_without_disclosing_titles(self):
        for matter in [self.secret, self.other_matter]:
            batch = self.stage(f"Pasta;Número\n{matter.pk};123-A\n", kind="cases", actor=self.manager)
            self.assertFalse(self.review(batch, actor=self.manager)["can_confirm"])
            with self.assertRaises(ValidationError):
                self.commit(batch, actor=self.manager)
        self.assertFalse(CourtCase.objects.exists())

    def test_access_changes_between_preview_and_confirm_are_checked_again(self):
        batch = self.stage(f"Pasta;Número\n{self.matter.pk};123-A\n", kind="cases", actor=self.manager)
        self.assertTrue(self.review(batch, actor=self.manager)["can_confirm"])
        self.matter.confidential = True
        self.matter.save()
        with self.assertRaises(ValidationError):
            self.commit(batch, actor=self.manager)
        self.assertFalse(CourtCase.objects.exists())

    def test_court_number_format_duplicates_are_blocked(self):
        CourtCase.objects.create(organization=self.org, matter=self.matter, number="0001234-56.2026.8.06.0001")
        batch = self.stage(f"Pasta;Número\n{self.matter.pk};00012345620268060001\n", kind="cases")
        with self.assertRaises(ValidationError):
            self.commit(batch)
        self.assertEqual(CourtCase.objects.count(), 1)

    def test_restricted_case_conflict_does_not_disclose_matter_or_record_details(self):
        CourtCase.objects.create(organization=self.org, matter=self.secret, number="SEGREDO-123", opposing_party="Parte sigilosa")
        batch = self.stage(f"Pasta;Número\n{self.matter.pk};SEGREDO-123\n", kind="cases", actor=self.manager)
        review = self.review(batch, actor=self.manager)
        self.assertFalse(review["can_confirm"])
        errors = " ".join(review["rows"][0]["errors"])
        self.assertIn("não está disponível para importação", errors)
        self.assertNotIn("duplicidade", errors)
        self.assertNotIn("existe", errors)
        self.assertNotIn(self.secret.title, errors)
        self.assertNotIn("Parte sigilosa", errors)
        with self.assertRaises(ValidationError):
            self.commit(batch, actor=self.manager)

    def test_roles_revocations_and_cross_user_batches_are_rejected(self):
        for actor in [self.operator, self.viewer, self.client_user, self.other]:
            with self.assertRaises(PermissionDenied):
                self.stage(actor=actor)
        batch = self.stage()
        with self.assertRaises(PreviewUnavailable):
            self.commit(batch, actor=self.manager)
        Membership.objects.filter(organization=self.org, user=self.owner).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.commit(batch)

    def test_expired_preview_cannot_commit_and_purge_preserves_receipts(self):
        receipt = self.stage()
        self.commit(receipt)
        expired = self.stage("Nome\nOutra Pessoa\n")
        ImportBatch.objects.filter(pk__in=[receipt.pk, expired.pk]).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            self.commit(expired)
        call_command("purge_import_previews", stdout=io.StringIO())
        self.assertTrue(ImportBatch.objects.filter(pk=receipt.pk).exists())
        self.assertFalse(ImportBatch.objects.filter(pk=expired.pk).exists())

    def test_parse_rejects_unknown_missing_duplicate_headers_and_extra_values(self):
        for text in ["Nome;Senha\nMaria;abc\n", "Telefone\n88999999999\n", "Nome;Name\nMaria;Silva\n", "Nome\nMaria;outro\n"]:
            with self.subTest(text=text), self.assertRaises(ValidationError):
                parse_upload(upload(text), "contacts")

    def test_bounded_file_rows_cells_encoding_and_format(self):
        invalid = [upload("Nome\n" + "X\n" * 501), upload("Nome\n" + "X" * 4001), upload("Nome\n" + "X" * (2 * 1024 * 1024)), upload("Nome\n", "dados.xls"), SimpleUploadedFile("dados.csv", b"Nome\nJo\xe3o\n")]
        for file in invalid:
            with self.subTest(name=file.name, size=file.size), self.assertRaises(ValidationError):
                parse_upload(file, "contacts")

    def test_csv_formulas_rejected_but_international_phone_allowed(self):
        for formula in ["=1+1", "@SUM(A1:A2)", "+cmd|' /C calc'!A0", "-SUM(A1:A2)"]:
            with self.assertRaises(ValidationError):
                parse_upload(upload("Nome\n" + formula + "\n"), "contacts")
        rows, _ = parse_upload(upload("Nome;Telefone\nPessoa;+55 88 99274-5456\n"), "contacts")
        self.assertEqual(rows[0]["data"]["phone"], "+55 88 99274-5456")

    def test_xlsx_values_dates_formulas_numeric_identifiers_and_extra_tabs(self):
        from datetime import date
        rows, columns = parse_upload(xlsx([["Nome", "Nascimento"], ["Pessoa Excel", date(1991, 1, 20)]]), "contacts")
        self.assertEqual(rows[0]["data"]["birth_date"], "1991-01-20")
        self.assertEqual(len(columns), 2)
        for file in [xlsx([["Nome"], ["=1+1"]]), xlsx([["Nome", "CPF"], ["Pessoa", 12345678900]]), xlsx([["Nome"], ["Pessoa"]], extra_sheet=["Outro dado"])]:
            with self.assertRaises(ValidationError):
                parse_upload(file, "contacts")

    def test_xlsx_excessive_expansion_and_external_links_rejected(self):
        import zipfile
        for entry, payload in [("xl/externalLinks/link.xml", b"<x/>"), ("large.xml", b"x" * (12 * 1024 * 1024 + 1)), ("xl/vbaProject.bin", b"macro")]:
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(entry, payload)
            with self.assertRaises(ValidationError):
                parse_upload(SimpleUploadedFile("evil.xlsx", output.getvalue()), "contacts")

    def test_no_partial_records_survive_later_failure(self):
        batch = self.stage("Nome\nUma Pessoa\nOutra Pessoa\n")
        from apps.legal.services import audit
        calls = 0
        def broken_audit(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated failure")
            return audit(**kwargs)
        with patch("apps.intake.services.audit", side_effect=broken_audit), self.assertRaises(RuntimeError):
            self.commit(batch)
        self.assertFalse(Contact.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())
        batch.refresh_from_db()
        self.assertIsNone(batch.committed_at)
        self.assertEqual(len(batch.rows), 2)

    def test_http_workflow_explicit_confirmation_and_private_receipt(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("intake:home"), {"kind": "contacts", "file": upload("Nome\nPessoa da Web\n")})
        batch = ImportBatch.objects.get()
        self.assertRedirects(response, reverse("intake:preview", args=[batch.pk]))
        self.assertFalse(Contact.objects.exists())
        self.assertEqual(self.client.get(reverse("intake:confirm", args=[batch.pk])).status_code, 405)
        self.assertEqual(self.client.post(reverse("intake:confirm", args=[batch.pk]), {}).status_code, 400)
        self.assertFalse(Contact.objects.exists())
        self.assertRedirects(self.client.post(reverse("intake:confirm", args=[batch.pk]), {"confirmed": "on"}), reverse("intake:preview", args=[batch.pk]))
        self.assertContains(self.client.get(reverse("intake:preview", args=[batch.pk])), "1 registro criado")
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("intake:preview", args=[batch.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("intake:discard", args=[batch.pk])).status_code, 404)

    def test_csrf_and_read_only_roles_and_private_cache_headers(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("intake:home"))
        self.assertContains(response, "Consultar IDs das pastas")
        self.assertIn("no-store", response["Cache-Control"])
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        self.assertEqual(browser.post(reverse("intake:home"), {"kind": "contacts", "file": upload("Nome\nPessoa\n")}).status_code, 403)
        for actor in [self.operator, self.viewer, self.client_user]:
            self.client.force_login(actor)
            self.assertEqual(self.client.get(reverse("intake:home")).status_code, 403)

    def test_template_downloads_and_discard_do_not_create_records(self):
        self.client.force_login(self.owner)
        for extension in ["csv", "xlsx"]:
            response = self.client.get(reverse("intake:template", args=["contacts", extension]))
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response["Content-Disposition"])
        batch = self.stage()
        self.assertRedirects(self.client.post(reverse("intake:discard", args=[batch.pk])), reverse("intake:home"))
        self.assertFalse(ImportBatch.objects.exists())
        self.assertFalse(Contact.objects.exists())

    @override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
    def test_inactive_subscription_blocks_service_and_start_supports_contacts(self):
        with self.assertRaises(PermissionDenied):
            self.stage()
        OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
        self.commit(self.stage())
        self.assertEqual(Contact.objects.count(), 1)

    def test_preview_count_is_bounded_and_expired_previews_are_cleaned_on_upload(self):
        for index in range(10):
            self.stage(f"Nome\nPessoa {index}\n")
        with self.assertRaises(ValidationError):
            self.stage()
        ImportBatch.objects.all().update(expires_at=timezone.now() - timedelta(seconds=1))
        self.stage()
        self.assertEqual(ImportBatch.objects.count(), 1)

    def test_discarded_preview_during_confirmation_returns_friendly_message_without_writes(self):
        batch = self.stage()
        self.client.force_login(self.owner)
        from .services import commit_import as actual_commit
        def raced_commit(**kwargs):
            ImportBatch.objects.filter(pk=batch.pk).delete()
            return actual_commit(**kwargs)
        with patch("apps.intake.views.commit_import", side_effect=raced_commit):
            response = self.client.post(reverse("intake:confirm", args=[batch.pk]), {"confirmed": "on"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Esta prévia não está mais disponível")
        self.assertFalse(Contact.objects.exists())
