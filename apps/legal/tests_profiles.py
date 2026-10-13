import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Membership, Organization
from apps.legal.forms import ContactForm
from apps.legal.models import Contact, Document, Matter
from apps.legal.services import add_document_version
from apps.portal.models import ClientAccess
from apps.portal.services import decide_review, grant_access, publish_version, request_review


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class ProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Perfis", slug="profiles-test", business_type="office")
        cls.other = Organization.objects.create(name="Outro", slug="other-profiles-test", business_type="office")
        for name, role, org in [("owner", "owner", cls.org), ("reviewer", "manager", cls.org), ("operator", "operator", cls.org), ("viewer", "viewer", cls.org), ("client_user", "client", cls.org), ("outsider", "owner", cls.other)]:
            user = get_user_model().objects.create_user(email=f"{name}-profiles@example.test", password="tests-only-pass")
            setattr(cls, name, user)
            setattr(cls, f"{name}_member", Membership.objects.create(organization=org, user=user, role=role))
        cls.contact = Contact.objects.create(organization=cls.org, name="Empresa Horizonte", kind="company", trade_name="Horizonte", address="Rua Um, 20", city="Fortaleza", representatives="Maria · administradora", notes="Contexto interno")
        cls.foreign_contact = Contact.objects.create(organization=cls.other, name="Cadastro externo")
        cls.matter = Matter.objects.create(organization=cls.org, title="Pasta pública do escritório", client=cls.contact, owner=cls.owner)
        cls.secret = Matter.objects.create(organization=cls.org, title="ASSUNTO SIGILOSO", client=cls.contact, owner=cls.owner, confidential=True)
        cls.foreign_matter = Matter.objects.create(organization=cls.other, title="Pasta externa", owner=cls.outsider)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = override_settings(PRIVATE_MEDIA_ROOT=directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.client.force_login(self.owner)

    def document(self, matter=None, actor=None):
        matter, actor = matter or self.matter, actor or self.owner
        doc = Document.objects.create(organization=matter.organization, matter=matter, title="Arquivo com histórico", kind="Prova", created_by=actor)
        first = add_document_version(document=doc, actor=actor, file=SimpleUploadedFile("primeiro.txt", b"primeira versao"))
        second = add_document_version(document=doc, actor=actor, file=SimpleUploadedFile("revisado.txt", b"segunda versao"))
        return doc, first, second

    def test_pf_and_pj_optional_fields_persist_without_granting_access(self):
        for kind in ["person", "company"]:
            with self.subTest(kind=kind):
                payload = {"name": "Pessoa teste", "kind": kind, "document": "123", "status": "prospect", "address": "Rua de teste, 1", "city": "Fortaleza", "country": "Brasil", "representatives": "Representante informado", "notes": "Nota interna"}
                payload.update({"birth_date": "1990-01-02", "profession": "Engenheira"} if kind == "person" else {"trade_name": "Teste Comércio", "state_registration": "ISENTO", "municipal_registration": "1234"})
                form = ContactForm(payload, organization=self.org, user=self.owner)
                self.assertTrue(form.is_valid(), form.errors)
                obj = form.save()
                obj.refresh_from_db()
                self.assertEqual(obj.city, "Fortaleza")
                self.assertEqual(obj.status, "prospect")
                self.assertFalse(ClientAccess.objects.filter(contact=obj).exists())

    def test_old_import_fields_still_work_and_status_is_preserved_when_omitted(self):
        self.contact.status = "inactive"
        self.contact.save()
        form = ContactForm({"name": "Empresa renomeada", "kind": "company"}, instance=self.contact, organization=self.org, user=self.owner)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().status, "inactive")
        self.assertEqual(form.instance.notes, "Contexto interno")
        fresh = ContactForm({"name": "Pessoa básica", "kind": "person"}, organization=self.org, user=self.owner)
        self.assertTrue(fresh.is_valid(), fresh.errors)
        self.assertEqual(fresh.save().status, "active")

    def test_company_birth_date_and_oversized_internal_notes_are_rejected(self):
        form = ContactForm({"name": "Empresa", "kind": "company", "birth_date": "1990-01-01", "notes": "a" * 6001}, organization=self.org, user=self.owner)
        self.assertFalse(form.is_valid())
        self.assertIn("birth_date", form.errors)
        self.assertIn("notes", form.errors)

    def test_contact_detail_uses_only_authorized_matters_and_hides_portal_management_from_viewer(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("legal:contact_detail", args=[self.contact.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.matter.title)
        self.assertNotContains(response, self.secret.title)
        self.assertEqual(response.context["matter_count"], 1)
        self.assertNotContains(response, "Vincular conta")
        self.assertNotContains(response, "Editar cadastro")
        self.assertEqual(self.client.get(reverse("legal:contact_detail", args=[self.foreign_contact.pk])).status_code, 404)

    def test_contact_form_has_sections_and_escapes_internal_notes(self):
        self.contact.notes = '<script>alert("x")</script>'
        self.contact.save()
        response = self.client.get(reverse("legal:contact_detail", args=[self.contact.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("x")</script>')
        form = self.client.get(reverse("legal:edit", args=["contacts", self.contact.pk]))
        self.assertContains(form, "Contexto do atendimento")
        self.assertContains(form, 'name="representatives"')

    def test_document_detail_preserves_every_version_and_uses_private_downloads(self):
        doc, first, second = self.document()
        response = self.client.get(reverse("legal:document_detail", args=[doc.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["latest_version"].pk, second.pk)
        self.assertEqual(response.context["version_count"], 2)
        for version in [first, second]:
            self.assertContains(response, version.checksum)
            self.assertContains(response, reverse("legal:document_download", args=[version.pk]))
            self.assertNotContains(response, version.file.name)
        self.assertContains(response, "não comprova uma assinatura")

    def test_document_access_is_rechecked_after_confidentiality_and_revocation(self):
        doc, _, _ = self.document()
        self.client.force_login(self.viewer)
        url = reverse("legal:document_detail", args=[doc.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.matter.confidential = True
        self.matter.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.matter.members.add(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.viewer_member.is_active = False
        self.viewer_member.save()
        self.assertNotEqual(self.client.get(url).status_code, 200)

    def test_viewer_sees_versions_without_staff_review_or_mutation_actions(self):
        doc, _, _ = self.document()
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("legal:document_detail", args=[doc.pk]))
        self.assertContains(response, "Histórico de versões")
        for caption in ["Solicitar revisão", "Nova versão", "Editar dados", "Criar tarefa na pasta", "Publicações"]:
            self.assertNotContains(response, caption)

    def test_document_shows_real_review_and_publication_state_for_authorized_staff(self):
        doc, first, _ = self.document()
        review = request_review(actor=self.owner, organization=self.org, version=first, reviewer=self.reviewer, note="Conferir dados")
        decide_review(actor=self.reviewer, review=review, outcome="approved", note="Conferido")
        access = grant_access(actor=self.owner, organization=self.org, membership=self.client_user_member, contact=self.contact)
        publication = publish_version(actor=self.owner, review=review, access=access, title="Documento publicado")
        response = self.client.get(reverse("legal:document_detail", args=[doc.pk]))
        self.assertContains(response, reverse("portal:review", args=[review.pk]))
        self.assertContains(response, reverse("portal:publication", args=[publication.pk]))
        self.assertContains(response, "Aprovado")
        self.assertEqual(response.context["review_count"], 1)
        self.assertEqual(response.context["publication_count"], 1)
        self.client_user.is_active = False
        self.client_user.save()
        for route, pk in [("document_detail", doc.pk), ("contact_detail", self.contact.pk)]:
            disabled = self.client.get(reverse("legal:" + route, args=[pk]))
            self.assertContains(disabled, "Acesso desativado")

    def test_portal_shortcut_prefills_only_currently_authorized_records(self):
        _, _, second = self.document()
        _, _, secret_version = self.document(self.secret)
        self.client.force_login(self.operator)
        for value, expected in [(str(second.pk), second.pk), (str(secret_version.pk), None), ("-1", None), ("x", None), ("9" * 40, None)]:
            response = self.client.get(reverse("portal:review_create"), {"version": value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["form"].initial.get("version"), expected)
        self.client.force_login(self.owner)
        for pk, expected in [(self.contact.pk, self.contact.pk), (self.foreign_contact.pk, None)]:
            response = self.client.get(reverse("portal:access_create"), {"contact": str(pk)})
            self.assertEqual(response.context["form"].initial.get("contact"), expected)
        response = self.client.post(reverse("portal:review_create") + f"?version={second.pk}", {"version": secret_version.pk})
        self.assertEqual(str(response.context["form"].data["version"]), str(secret_version.pk))

    def test_client_and_other_office_cannot_open_internal_profiles(self):
        doc, _, _ = self.document()
        for user, status in [(self.client_user, 403), (self.outsider, 404)]:
            self.client.force_login(user)
            for route, pk in [("contact_detail", self.contact.pk), ("document_detail", doc.pk)]:
                self.assertEqual(self.client.get(reverse("legal:" + route, args=[pk])).status_code, status)

    def test_profiles_are_get_only_and_anonymous_requires_login(self):
        doc, _, _ = self.document()
        for route, pk in [("contact_detail", self.contact.pk), ("document_detail", doc.pk)]:
            url = reverse("legal:" + route, args=[pk])
            self.assertEqual(self.client.post(url, {}).status_code, 405)
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302)
            self.client.force_login(self.owner)
