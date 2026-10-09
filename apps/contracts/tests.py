import io
import tempfile
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.models import Contact, Document, DocumentVersion, Matter
from .models import Contract, ContractRevision, ContractTemplate
from .services import generate_revision, make_docx, render_body, visible_contracts


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class ContractBuilderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Escritório de teste", slug="contratos-teste", business_type="office")
        cls.other = Organization.objects.create(name="Outro escritório", slug="contratos-outro", business_type="office")
        cls.owner = get_user_model().objects.create_user(email="contratos-owner@example.test", password="contract-test-only")
        cls.operator = get_user_model().objects.create_user(email="contratos-operator@example.test", password="contract-test-only")
        cls.viewer = get_user_model().objects.create_user(email="contratos-viewer@example.test", password="contract-test-only")
        cls.outsider = get_user_model().objects.create_user(email="contratos-other@example.test", password="contract-test-only")
        for user, role in [(cls.owner, "owner"), (cls.operator, "operator"), (cls.viewer, "viewer")]:
            Membership.objects.create(organization=cls.org, user=user, role=role)
        Membership.objects.create(organization=cls.other, user=cls.outsider, role="owner")
        cls.contact = Contact.objects.create(organization=cls.org, name="Pessoa fictícia", document="CPF de teste")
        cls.other_contact = Contact.objects.create(organization=cls.other, name="Pessoa externa")
        cls.matter = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Pasta permitida")
        cls.secret = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Pasta sigilosa", confidential=True)
        cls.other_matter = Matter.objects.create(organization=cls.other, owner=cls.outsider, client=cls.other_contact, title="Pasta externa")
        cls.template = ContractTemplate.objects.create(organization=cls.org, created_by=cls.owner, name="Modelo de teste", body="Contratante [[cliente_nome]]. Objeto: [[objeto]].")
        cls.other_template = ContractTemplate.objects.create(organization=cls.other, created_by=cls.outsider, name="Modelo externo", body="Texto externo")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.override = override_settings(PRIVATE_MEDIA_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.override.disable)
        self.client.force_login(self.owner)

    def generate(self, **kwargs):
        payload = dict(actor=self.owner, organization=self.org, template=self.template, matter=self.matter, client=self.contact, title="Contrato fictício", source_body=self.template.body, values={"cliente_nome": "Pessoa fictícia", "objeto": "Descrição editável"})
        payload.update(kwargs)
        return generate_revision(**payload)

    def post_data(self, **kwargs):
        payload = {"operation_key": str(uuid.uuid4()), "matter": self.matter.pk, "client": self.contact.pk, "title": "Contrato pela tela", "source_body": self.template.body, "value_cliente_nome": "Pessoa fictícia", "value_objeto": "Serviço descrito para teste", "reviewed": "on", "action": "generate"}
        payload.update(kwargs)
        return payload

    def test_real_generation_preserves_docx_and_immutable_revision(self):
        first = self.generate()
        self.assertEqual(first.document_version.document.matter_id, self.matter.pk)
        self.assertEqual(DocumentVersion.objects.count(), 1)
        with first.document_version.file.open("rb") as stream:
            payload = stream.read()
        self.assertEqual(payload, make_docx(first.title, first.rendered_text))
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name in archive.namelist():
                ElementTree.fromstring(archive.read(name))
            self.assertIn("Pessoa fictícia", archive.read("word/document.xml").decode())
        for mutation in [lambda: ContractRevision.objects.filter(pk=first.pk).update(title="Outro"), lambda: first.delete(), lambda: ContractRevision.objects.filter(pk=first.pk).delete()]:
            with self.assertRaises(ValidationError):
                mutation()
        first.rendered_text = "Alterado"
        with self.assertRaises(ValidationError):
            first.save()

    def test_model_edit_does_not_change_previous_document_and_revision(self):
        first = self.generate()
        original_hash = first.checksum
        self.template.body = "Modelo alterado [[cliente_nome]]"
        self.template.save()
        second = self.generate(contract=first.contract, source_body="Nova redação [[cliente_nome]]", title="Título revisado")
        first.refresh_from_db()
        self.assertEqual(first.checksum, original_hash)
        self.assertIn("Objeto:", first.rendered_text)
        self.assertEqual(second.number, 2)
        self.assertEqual(first.contract.revisions.count(), 2)
        self.assertTrue(Path(first.document_version.file.path).is_file())

    def test_interpolation_is_literal_and_does_not_execute_html_or_template_code(self):
        malicious = '<script>alert(1)</script>{{ request.user.password }}[[objeto]]'
        revision = self.generate(values={"cliente_nome": malicious, "objeto": "Seguro"})
        self.assertIn(malicious, revision.rendered_text)
        self.assertEqual(render_body("{{ secret }} [[cliente_nome]]", {"cliente_nome": "{{ config }}"}), "{{ secret }} {{ config }}")
        response = self.client.get(reverse("contracts:print", args=[revision.pk]))
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertIn("default-src 'none'", response["Content-Security-Policy"])
        with zipfile.ZipFile(io.BytesIO(make_docx("A < B", malicious))) as archive:
            xml = archive.read("word/document.xml")
            ElementTree.fromstring(xml)
            self.assertIn(b"&lt;script&gt;", xml)

    def test_invalid_missing_and_malformed_placeholders_block_generation(self):
        for body, values in [("[[nao_cadastrado]]", {}), ("[[cliente_nome]]", {}), ("[[ cliente_nome ]]", {"cliente_nome": "Nome"}), ("Texto\x00", {})]:
            with self.subTest(body=body), self.assertRaises(ValidationError):
                self.generate(source_body=body, values=values)
        self.assertFalse(Contract.objects.exists())
        self.assertFalse(Document.objects.exists())

    def test_generation_without_variables_is_supported(self):
        revision = self.generate(source_body="Rascunho inteiramente manual.", values={})
        self.assertEqual(revision.rendered_text, "Rascunho inteiramente manual.")

    def test_tenant_and_confidentiality_in_services_and_direct_urls(self):
        revision = self.generate(matter=self.secret)
        self.client.force_login(self.operator)
        for url in [reverse("contracts:detail", args=[revision.contract_id]), reverse("contracts:print", args=[revision.pk]), reverse("contracts:download", args=[revision.pk]), reverse("contracts:revise", args=[revision.contract_id]), reverse("contracts:template_edit", args=[self.other_template.pk])]:
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, [403, 404])
        self.assertFalse(visible_contracts(self.operator, self.org).exists())
        with self.assertRaises(PermissionDenied):
            self.generate(actor=self.operator, matter=self.secret)
        with self.assertRaises(PermissionDenied):
            self.generate(template=self.other_template)
        with self.assertRaises(ValidationError):
            self.generate(client=self.other_contact)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("contracts:detail", args=[revision.contract_id])).status_code, 404)

    def test_viewer_read_only_and_operator_cannot_manage_templates(self):
        revision = self.generate()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("contracts:detail", args=[revision.contract_id])).status_code, 200)
        self.assertEqual(self.client.post(reverse("contracts:build", args=[self.template.pk]), self.post_data()).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.generate(actor=self.viewer)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse("contracts:template_create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("contracts:template_archive", args=[self.template.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("contracts:build", args=[self.template.pk]), self.post_data()).status_code, 302)

    def test_request_tampering_rejects_foreign_identifiers(self):
        url = reverse("contracts:build", args=[self.template.pk])
        for override in [{"matter": self.other_matter.pk}, {"client": self.other_contact.pk}]:
            with self.subTest(override=override):
                self.assertEqual(self.client.post(url, self.post_data(**override)).status_code, 200)
                self.assertFalse(Contract.objects.exists())
        self.client.force_login(self.operator)
        self.assertEqual(self.client.post(url, self.post_data(matter=self.secret.pk)).status_code, 200)
        self.assertFalse(Contract.objects.exists())

    def test_server_preview_requires_review_then_preserves_generation(self):
        url = reverse("contracts:build", args=[self.template.pk])
        response = self.client.post(url, self.post_data(action="preview"))
        self.assertContains(response, "Serviço descrito para teste")
        self.assertFalse(Contract.objects.exists())
        self.client.post(url, self.post_data(reviewed=""))
        self.assertFalse(Contract.objects.exists())
        response = self.client.post(url, self.post_data(organization=self.other.pk))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Contract.objects.get().organization, self.org)

    def test_repeated_operation_is_idempotent_and_rejects_repurposing(self):
        key = uuid.uuid4()
        first = self.generate(operation_key=key)
        second = self.generate(operation_key=key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(DocumentVersion.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.generate(operation_key=key, title="Título adulterado")

    def test_rollback_removes_new_file_without_touching_existing_versions(self):
        first = self.generate()
        with patch("apps.contracts.services.ContractRevision.objects.create", side_effect=ValidationError("falha simulada")):
            with self.assertRaises(ValidationError):
                self.generate(contract=first.contract)
        self.assertEqual(DocumentVersion.objects.count(), 1)
        self.assertEqual(len(list(Path(self.directory.name).rglob("*.docx"))), 1)
        self.assertTrue(Path(first.document_version.file.path).exists())

    def test_anonymous_download_csrf_and_post_only_archive(self):
        revision = self.generate()
        self.client.logout()
        self.assertEqual(self.client.get(reverse("contracts:download", args=[revision.pk])).status_code, 302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("contracts:template_archive", args=[self.template.pk])).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(reverse("contracts:build", args=[self.template.pk]), self.post_data()).status_code, 403)

    @override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True)
    def test_start_inactive_and_quota_block_real_generation(self):
        subscription = OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
        self.assertEqual(self.client.get(reverse("contracts:library")).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.generate()
        subscription.plan = "max"
        subscription.status = "pending"
        subscription.save()
        with self.assertRaises(PermissionDenied):
            self.generate()
        subscription.status = "active"
        subscription.save()
        with patch.dict("apps.billing.plans.PLANS", {"max": {"name": "Max", "advanced": True, "members": 15, "matters": 1000, "versions": 0}}):
            with self.assertRaises(ValidationError):
                self.generate()
        self.assertFalse(Document.objects.exists())

    def test_download_contains_current_private_snapshot(self):
        revision = self.generate()
        response = self.client.get(reverse("contracts:download", args=[revision.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        data = b"".join(response.streaming_content)
        self.assertEqual(data, make_docx(revision.title, revision.rendered_text))

    def test_pages_templates_archive_and_existing_revision_are_real(self):
        revision = self.generate()
        for url in [reverse("contracts:library"), reverse("contracts:history"), reverse("contracts:template_create") + "?exemplo=1", reverse("contracts:template_edit", args=[self.template.pk]), reverse("contracts:build", args=[self.template.pk]), reverse("contracts:detail", args=[revision.contract_id]), reverse("contracts:revise", args=[revision.contract_id])]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(reverse("contracts:template_create"), {"name": "Modelo novo", "body": "Olá [[cliente_nome]]", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ContractTemplate.objects.filter(name="Modelo novo", organization=self.org).exists())
        self.client.post(reverse("contracts:template_archive", args=[self.template.pk]))
        self.assertEqual(self.client.get(reverse("contracts:build", args=[self.template.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("contracts:detail", args=[revision.contract_id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("contracts:revise", args=[revision.contract_id])).status_code, 200)
