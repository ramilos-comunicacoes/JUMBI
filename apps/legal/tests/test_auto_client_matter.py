from datetime import date
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Membership, Organization
from apps.legal.models import AuditEvent, Contact, Matter
from apps.legal.services import ensure_client_matter
from apps.intake.services import commit_import, stage_import
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class AutoClientMatterTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Escritório Alfa Auto",
            slug="alfa-auto",
            business_type="office",
            practice_areas=["previdenciario", "civil"],
        )
        self.user = User.objects.create_user(
            email="advogado@alfa.test",
            password="testpassword123",
            first_name="Dr.",
            last_name="Advogado",
        )
        self.membership = Membership.objects.create(
            organization=self.org,
            user=self.user,
            role="owner",
        )
        self.client.login(username="advogado@alfa.test", password="testpassword123")

    def test_ensure_client_matter_creates_matter_with_office_primary_area(self):
        contact = Contact.objects.create(
            organization=self.org,
            name="Mariana Souza",
            document="12345678901",
        )
        matter = ensure_client_matter(contact=contact, actor=self.user)
        self.assertIsNotNone(matter)
        self.assertEqual(matter.client, contact)
        self.assertEqual(matter.title, "Pasta Geral · Mariana Souza")
        self.assertEqual(matter.owner, self.user)
        self.assertEqual(matter.area, "Direito Previdenciário")
        self.assertEqual(matter.status, Matter.Status.ACTIVE)

        # Calling again is idempotent and does not create duplicate matter
        again = ensure_client_matter(contact=contact, actor=self.user)
        self.assertEqual(again.pk, matter.pk)
        self.assertEqual(Matter.objects.filter(client=contact).count(), 1)

    def test_manual_contact_creation_in_ui_automatically_creates_matter(self):
        url = reverse("legal:create", args=["contacts"])
        response = self.client.post(url, {
            "name": "Carlos Roberto Silva",
            "kind": "person",
            "document": "98765432100",
            "email": "carlos@silva.test",
            "phone": "85999998888",
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        contact = Contact.objects.filter(organization=self.org, name="Carlos Roberto Silva").first()
        self.assertIsNotNone(contact)

        # Assert matter was automatically created
        matter = Matter.objects.filter(organization=self.org, client=contact).first()
        self.assertIsNotNone(matter)
        self.assertEqual(matter.title, "Pasta Geral · Carlos Roberto Silva")
        self.assertEqual(matter.owner, self.user)
        self.assertEqual(matter.area, "Direito Previdenciário")

        # Verify contact detail shows this matter
        detail_url = reverse("legal:contact_detail", args=[contact.pk])
        resp_detail = self.client.get(detail_url)
        self.assertContains(resp_detail, "Pasta Geral · Carlos Roberto Silva")

    def test_editing_contact_does_not_create_duplicate_matter(self):
        contact = Contact.objects.create(organization=self.org, name="Beatriz Ramos")
        ensure_client_matter(contact=contact, actor=self.user)
        self.assertEqual(Matter.objects.filter(client=contact).count(), 1)

        edit_url = reverse("legal:edit", args=["contacts", contact.pk])
        response = self.client.post(edit_url, {
            "name": "Beatriz Ramos Alterada",
            "kind": "person",
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        # Still only 1 matter
        self.assertEqual(Matter.objects.filter(client=contact).count(), 1)

    def test_intake_import_contacts_automatically_creates_matter_for_each_client(self):
        csv_content = (
            "Nome;Tipo de pessoa;CPF / CNPJ;E-mail;Telefone\n"
            "José Ferreira;Pessoa física;11122233344;jose@test.local;85988887777\n"
            "Antônio Carlos;Pessoa física;55566677788;antonio@test.local;85977776666\n"
        )
        upload_file = SimpleUploadedFile("clientes.csv", csv_content.encode("utf-8-sig"), content_type="text/csv")
        batch = stage_import(actor=self.user, organization=self.org, kind="contacts", upload=upload_file)

        committed, created = commit_import(actor=self.user, organization=self.org, batch_id=batch.pk)
        self.assertTrue(created)
        self.assertEqual(committed.created_count, 2)

        # Assert both contacts exist
        c1 = Contact.objects.filter(organization=self.org, name="José Ferreira").first()
        c2 = Contact.objects.filter(organization=self.org, name="Antônio Carlos").first()
        self.assertIsNotNone(c1)
        self.assertIsNotNone(c2)

        # Assert matters were automatically created for both
        m1 = Matter.objects.filter(organization=self.org, client=c1).first()
        m2 = Matter.objects.filter(organization=self.org, client=c2).first()
        self.assertIsNotNone(m1)
        self.assertIsNotNone(m2)
        self.assertEqual(m1.title, "Pasta Geral · José Ferreira")
        self.assertEqual(m2.title, "Pasta Geral · Antônio Carlos")

    def test_matter_creation_with_client_query_param_preselects_client(self):
        contact = Contact.objects.create(organization=self.org, name="Cliente Pré-selecionado")
        url = reverse("legal:create", args=["matters"]) + f"?client={contact.pk}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["form"].initial.get("client"), contact.pk)
