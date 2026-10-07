from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog, Membership, Organization, User
from apps.office.models import Client, LegalCase, PracticeArea

from .models import (
    Partner,
    PartnerCampaign,
    PartnerCategory,
    PartnerNetworkSettings,
    PartnerOpportunity,
)


@override_settings(DEBUG=True, ALLOWED_HOSTS=["testserver"], JUMBI_LEGAL_ONLY=True)
class PartnerNetworkTests(TestCase):
    password = "Rede-Jumbi!2026#Segura"

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Jumbi Advocacia Parceiros",
            slug="jumbi-advocacia-parceiros",
            business_type=Organization.BusinessType.OFFICE,
        )
        self.owner = User.objects.create_user(
            email="owner-partners@example.com",
            password=self.password,
        )
        Membership.objects.create(
            organization=self.organization,
            user=self.owner,
            role=Membership.Role.OWNER,
        )
        self.network = PartnerNetworkSettings.objects.create(
            organization=self.organization,
            is_enabled=True,
            compliance_acknowledged=True,
            compliance_acknowledged_by=self.owner,
        )
        self.category = PartnerCategory.objects.create(
            organization=self.organization,
            name="Contabilidade",
        )
        self.partner_user = User.objects.create_user(
            email="partner@example.com",
            password=self.password,
        )
        self.partner = Partner.objects.create(
            organization=self.organization,
            user=self.partner_user,
            category=self.category,
            display_name="Contabilidade Segura",
            email=self.partner_user.email,
            phone="5585999999999",
            status=Partner.Status.APPROVED,
            terms_accepted_at=timezone.now(),
            privacy_accepted_at=timezone.now(),
        )

    def test_partner_login_routes_only_to_external_portal(self):
        response = self.client.post(
            reverse("core:login"),
            {"username": self.partner_user.email, "password": self.password},
        )

        self.assertRedirects(response, reverse("partners:portal"))
        self.assertEqual(self.client.get(reverse("partners:portal")).status_code, 200)
        self.assertEqual(self.client.get(reverse("office:workspace")).status_code, 403)
        self.assertFalse(Membership.objects.filter(user=self.partner_user).exists())

    def test_blocked_partner_cannot_log_in(self):
        self.partner.status = Partner.Status.BLOCKED
        self.partner.save(update_fields=["status"])

        response = self.client.post(
            reverse("core:login"),
            {"username": self.partner_user.email, "password": self.password},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "não possui um ambiente Jumbi Jurídico ativo ou portal de parceiros ativo")

    def test_viewer_cannot_open_partner_network_data(self):
        viewer = User.objects.create_user(email="viewer-partners@example.com", password=self.password)
        Membership.objects.create(
            organization=self.organization,
            user=viewer,
            role=Membership.Role.VIEWER,
        )
        self.client.force_login(viewer)

        response = self.client.get(reverse("office:section", args=["partners"]))

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, self.partner.email, status_code=403)

    def test_owner_can_open_and_configure_partner_network(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("office:section", args=["partners"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rede de Parceiros")
        self.assertContains(response, "Infraestrutura, não captação")

        response = self.client.post(
            reverse("office:section", args=["partners"]),
            {
                "action": "partner_network",
                "network-is_enabled": "on",
                "network-public_name": "Rede Horizonte",
                "network-presentation": "Relacionamento responsável.",
                "network-acceptance_rules": "Consentimento e pertinência.",
                "network-relationship_policy": "Sem captação indevida.",
                "network-privacy_notice_version": "2.0",
                "network-compliance_confirmation": "on",
            },
        )
        self.assertRedirects(response, reverse("office:section", args=["partners"]))
        self.network.refresh_from_db()
        self.assertEqual(self.network.public_name, "Rede Horizonte")
        self.assertTrue(
            AuditLog.objects.filter(
                organization=self.organization,
                action="partners.network.updated",
            ).exists()
        )

    def test_owner_provisions_partner_without_internal_membership(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("office:section", args=["partners"]),
            {
                "action": "partner",
                "partner-person_type": Partner.PersonType.COMPANY,
                "partner-display_name": "Associação Modelo",
                "partner-legal_name": "Associação Modelo",
                "partner-document_number": "12.345.678/0001-90",
                "partner-category": self.category.id,
                "partner-email": "associacao@example.com",
                "partner-phone": "85988887777",
                "partner-whatsapp": "85988887777",
                "partner-city": "Fortaleza",
                "partner-state": "ce",
                "partner-origin": "Relacionamento institucional",
                "partner-temporary_password": self.password,
            },
        )

        self.assertRedirects(response, reverse("office:section", args=["partners"]))
        created = Partner.objects.get(email="associacao@example.com")
        self.assertEqual(created.status, Partner.Status.PENDING)
        self.assertEqual(created.state, "CE")
        self.assertTrue(created.document_hash)
        self.assertFalse(Membership.objects.filter(user=created.user).exists())

    def test_partner_submits_consented_opportunity_and_duplicate_is_flagged(self):
        self.client.force_login(self.partner_user)
        area = PracticeArea.objects.get(slug="civil")
        payload = {
            "action": "opportunity",
            "opportunity-practice_area": area.id,
            "opportunity-interested_party_name": "Maria da Silva",
            "opportunity-email": "maria@example.com",
            "opportunity-phone": "85990001111",
            "opportunity-city": "Fortaleza",
            "opportunity-state": "ce",
            "opportunity-document_number": "123.456.789-01",
            "opportunity-description": "Necessita análise inicial de contrato.",
            "opportunity-source": "Relacionamento profissional",
            "opportunity-consent_confirmed": "on",
        }

        response = self.client.post(reverse("partners:portal"), payload)
        self.assertRedirects(response, reverse("partners:portal"))
        first = PartnerOpportunity.objects.get()
        self.assertEqual(first.status, PartnerOpportunity.Status.NEW)
        self.assertTrue(first.consent_confirmed)
        self.assertTrue(first.document_hash)
        self.assertFalse(first.possible_duplicate)

        payload["opportunity-interested_party_name"] = "Maria da Silva Segundo Registro"
        response = self.client.post(reverse("partners:portal"), payload)
        self.assertRedirects(response, reverse("partners:portal"))
        duplicate = PartnerOpportunity.objects.latest("id")
        self.assertEqual(duplicate.status, PartnerOpportunity.Status.DUPLICATE)
        self.assertTrue(duplicate.possible_duplicate)

    def test_partner_sees_only_own_opportunities_and_no_internal_note(self):
        other_user = User.objects.create_user(email="other-partner@example.com", password=self.password)
        other_partner = Partner.objects.create(
            organization=self.organization,
            user=other_user,
            display_name="Outro Parceiro",
            email=other_user.email,
            status=Partner.Status.APPROVED,
        )
        PartnerOpportunity.objects.create(
            organization=self.organization,
            partner=self.partner,
            interested_party_name="Registro Visível",
            email="visible@example.com",
            description="Descrição autorizada.",
            partner_message="Mensagem pública segura.",
            internal_notes="Estratégia interna sigilosa.",
        )
        PartnerOpportunity.objects.create(
            organization=self.organization,
            partner=other_partner,
            interested_party_name="Registro de Outro Parceiro",
            email="other@example.com",
            description="Não deve aparecer.",
        )
        self.client.force_login(self.partner_user)

        response = self.client.get(reverse("partners:portal"))

        self.assertContains(response, "Registro Visível")
        self.assertContains(response, "Mensagem pública segura")
        self.assertNotContains(response, "Estratégia interna sigilosa")
        self.assertNotContains(response, "Registro de Outro Parceiro")

    def test_manager_updates_then_converts_opportunity_with_audit(self):
        manager = User.objects.create_user(email="manager-partners@example.com", password=self.password)
        Membership.objects.create(
            organization=self.organization,
            user=manager,
            role=Membership.Role.MANAGER,
        )
        opportunity = PartnerOpportunity.objects.create(
            organization=self.organization,
            partner=self.partner,
            interested_party_name="Cliente Convertido",
            email="convertido@example.com",
            description="Demanda jurídica qualificada.",
        )
        self.client.force_login(manager)

        response = self.client.post(
            reverse("partners:opportunity-status", args=[opportunity.id]),
            {
                "status": PartnerOpportunity.Status.ANALYSIS,
                "public_message": "Triagem iniciada.",
                "internal_message": "Revisar documentação.",
            },
        )
        self.assertRedirects(response, reverse("office:section", args=["partners"]))
        opportunity.refresh_from_db()
        self.assertEqual(opportunity.status, PartnerOpportunity.Status.ANALYSIS)

        response = self.client.post(
            reverse("partners:opportunity-convert", args=[opportunity.id]),
        )
        self.assertRedirects(response, reverse("office:section", args=["partners"]))
        opportunity.refresh_from_db()
        self.assertEqual(opportunity.status, PartnerOpportunity.Status.CASE_CREATED)
        self.assertEqual(Client.objects.filter(organization=self.organization).count(), 1)
        self.assertEqual(LegalCase.objects.filter(organization=self.organization).count(), 1)
        self.assertTrue(
            AuditLog.objects.filter(
                organization=self.organization,
                action="partners.opportunity.converted",
            ).exists()
        )

    def test_cross_tenant_partner_status_change_is_rejected(self):
        other_organization = Organization.objects.create(
            name="Outro Escritório",
            slug="outro-escritorio-parceiros",
            business_type=Organization.BusinessType.OFFICE,
        )
        other_owner = User.objects.create_user(email="other-owner@example.com", password=self.password)
        Membership.objects.create(
            organization=other_organization,
            user=other_owner,
            role=Membership.Role.OWNER,
        )
        self.client.force_login(other_owner)

        response = self.client.post(
            reverse("partners:partner-status", args=[self.partner.id]),
            {"status": Partner.Status.BLOCKED},
        )

        self.assertEqual(response.status_code, 400)
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.status, Partner.Status.APPROVED)

    def test_financial_policy_requires_documented_basis_and_has_no_automatic_commission(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("office:section", args=["partners"]),
            {
                "action": "partner_network",
                "network-is_enabled": "on",
                "network-public_name": "Rede de Parceiros",
                "network-presentation": "Rede responsável.",
                "network-privacy_notice_version": "1.0",
                "network-financial_policy_enabled": "on",
                "network-compliance_confirmation": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Descreva a base contratual")
        field_names = {field.name for field in PartnerOpportunity._meta.fields}
        self.assertNotIn("commission", field_names)
        self.assertNotIn("commission_percentage", field_names)
