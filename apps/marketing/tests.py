from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Organization, Membership
from apps.legal.models import Contact, Matter
from .models import Campaign, Lead, LeadStage, MarketingExpense, MarketingChannel, CampaignStatus
from .services import (
    calculate_marketing_kpis,
    get_funnel_summary,
    get_channel_summary,
    convert_lead_to_client,
)

User = get_user_model()


class MarketingModuleTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="advogado@jumbi.teste",
            password="SenhaForte1234!",
            first_name="Dr. João",
        )
        self.org = Organization.objects.create(
            name="Escritório Teste Marketing",
            business_type=Organization.BusinessType.OFFICE,
            status=Organization.Status.ACTIVE,
        )
        self.membership = Membership.objects.create(
            organization=self.org,
            user=self.user,
            role=Membership.Role.OWNER,
            is_active=True,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_campaign_creation_and_properties(self):
        campaign = Campaign.objects.create(
            organization=self.org,
            name="Meta Ads - Previdenciário 2026",
            channel=MarketingChannel.META_ADS,
            budget=Decimal("2000.00"),
            spent=Decimal("1000.00"),
            status=CampaignStatus.ATIVA,
            created_by=self.user,
        )

        lead1 = Lead.objects.create(
            organization=self.org,
            campaign=campaign,
            name="Maria Santos",
            phone="85999990001",
            channel=MarketingChannel.META_ADS,
            stage=LeadStage.CONVERTIDO,
            estimated_value=Decimal("4500.00"),
            closed_value=Decimal("4500.00"),
        )
        lead2 = Lead.objects.create(
            organization=self.org,
            campaign=campaign,
            name="José Ferreira",
            phone="85999990002",
            channel=MarketingChannel.META_ADS,
            stage=LeadStage.NOVO,
            estimated_value=Decimal("3000.00"),
        )

        self.assertEqual(campaign.total_leads_count, 2)
        self.assertEqual(campaign.converted_leads_count, 1)
        self.assertEqual(campaign.conversion_rate, Decimal("50.0"))
        self.assertEqual(campaign.cost_per_lead, Decimal("500.00"))
        self.assertEqual(campaign.cost_per_acquisition, Decimal("1000.00"))
        self.assertEqual(campaign.total_revenue, Decimal("4500.00"))
        self.assertEqual(campaign.roas, Decimal("4.5"))

    def test_calculate_marketing_kpis(self):
        campaign = Campaign.objects.create(
            organization=self.org,
            name="Google Ads - BPC LOAS",
            channel=MarketingChannel.GOOGLE_ADS,
            budget=Decimal("1500.00"),
            spent=Decimal("600.00"),
            status=CampaignStatus.ATIVA,
        )

        Lead.objects.create(
            organization=self.org,
            campaign=campaign,
            name="Ana Paula",
            phone="85999990003",
            channel=MarketingChannel.GOOGLE_ADS,
            stage=LeadStage.CONVERTIDO,
            closed_value=Decimal("3600.00"),
        )
        Lead.objects.create(
            organization=self.org,
            campaign=campaign,
            name="Carlos Alberto",
            phone="85999990004",
            channel=MarketingChannel.GOOGLE_ADS,
            stage=LeadStage.CONTATO,
            estimated_value=Decimal("2000.00"),
        )

        # Standalone expense
        MarketingExpense.objects.create(
            organization=self.org,
            title="Software de automação WhatsApp",
            category=MarketingExpense.ExpenseCategory.SOFTWARE,
            amount=Decimal("200.00"),
            date=timezone.now().date(),
        )

        kpis = calculate_marketing_kpis(self.org)
        # Total spent: 600 (campaign) + 200 (standalone) = 800
        self.assertEqual(kpis["total_spent"], Decimal("800.00"))
        self.assertEqual(kpis["total_revenue"], Decimal("3600.00"))
        self.assertEqual(kpis["total_leads"], 2)
        self.assertEqual(kpis["converted_leads"], 1)
        self.assertEqual(kpis["cac"], Decimal("800.00"))
        self.assertEqual(kpis["roas"], Decimal("4.50"))
        self.assertEqual(kpis["avg_ticket"], Decimal("3600.00"))
        self.assertEqual(kpis["pipeline_value"], Decimal("2000.00"))

    def test_convert_lead_to_client_and_matter(self):
        lead = Lead.objects.create(
            organization=self.org,
            name="Sebastião Pinheiro",
            phone="85988887777",
            email="sebastiao@exemplo.com",
            channel=MarketingChannel.META_ADS,
            legal_area="previdenciario",
            stage=LeadStage.QUALIFICADO,
            estimated_value=Decimal("5000.00"),
        )

        contact, matter = convert_lead_to_client(lead, actor=self.user)

        self.assertIsNotNone(contact)
        self.assertEqual(contact.name, "Sebastião Pinheiro")
        self.assertEqual(contact.phone, "85988887777")
        self.assertEqual(contact.organization, self.org)

        self.assertIsNotNone(matter)
        self.assertEqual(matter.client, contact)
        self.assertEqual(matter.organization, self.org)
        self.assertEqual(matter.area, "previdenciario")

        lead.refresh_from_db()
        self.assertEqual(lead.stage, LeadStage.CONVERTIDO)
        self.assertEqual(lead.converted_contact, contact)
        self.assertEqual(lead.converted_matter, matter)
        self.assertEqual(lead.closed_value, Decimal("5000.00"))
        self.assertIsNotNone(lead.converted_at)

    def test_marketing_dashboard_view(self):
        response = self.client.get(reverse("marketing:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Marketing Jurídico")
        self.assertContains(response, "CAC Médio")
        self.assertContains(response, "ROAS")

    def test_marketing_kanban_view_and_filter(self):
        Lead.objects.create(
            organization=self.org,
            name="Lead Filtrado",
            phone="85911112222",
            channel=MarketingChannel.WHATSAPP,
            stage=LeadStage.NOVO,
        )

        response = self.client.get(reverse("marketing:leads_kanban"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lead Filtrado")

        # Test HTMX filter
        response_htmx = self.client.get(
            reverse("marketing:leads_kanban"),
            {"q": "Lead Filtrado"},
            HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response_htmx.status_code, 200)
        self.assertContains(response_htmx, "Lead Filtrado")

    def test_utm_builder_view(self):
        response = self.client.get(reverse("marketing:utm_builder"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gerador de Links UTM")
