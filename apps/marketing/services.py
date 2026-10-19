from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.utils import timezone
from .models import Campaign, Lead, LeadStage, MarketingExpense, MarketingChannel


def calculate_marketing_kpis(organization):
    """Calculate executive marketing performance metrics for the organization."""
    campaigns = Campaign.objects.filter(organization=organization)
    leads = Lead.objects.filter(organization=organization)
    expenses = MarketingExpense.objects.filter(organization=organization)

    # Calculate total invested: sum of campaign spent + any standalone expenses
    campaign_spent = campaigns.aggregate(total=Sum("spent"))["total"] or Decimal("0.00")
    expenses_total = expenses.filter(campaign__isnull=True).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    total_spent = campaign_spent + expenses_total

    total_leads = leads.count()
    converted_leads = leads.filter(stage=LeadStage.CONVERTIDO).count()
    active_pipeline_leads = leads.exclude(stage__in=[LeadStage.CONVERTIDO, LeadStage.PERDIDO]).count()

    total_revenue = leads.filter(stage=LeadStage.CONVERTIDO).aggregate(total=Sum("closed_value"))["total"] or Decimal("0.00")
    pipeline_value = leads.exclude(stage__in=[LeadStage.CONVERTIDO, LeadStage.PERDIDO]).aggregate(total=Sum("estimated_value"))["total"] or Decimal("0.00")

    cac = Decimal("0.00")
    if converted_leads > 0 and total_spent > 0:
        cac = round(total_spent / Decimal(converted_leads), 2)

    roas = Decimal("0.0")
    if total_spent > 0:
        roas = round(total_revenue / total_spent, 2)

    roi_percent = Decimal("0.0")
    if total_spent > 0:
        roi_percent = round(((total_revenue - total_spent) / total_spent) * Decimal("100"), 1)

    cpl = Decimal("0.00")
    if total_leads > 0 and total_spent > 0:
        cpl = round(total_spent / Decimal(total_leads), 2)

    conversion_rate = Decimal("0.0")
    if total_leads > 0:
        conversion_rate = round((Decimal(converted_leads) / Decimal(total_leads)) * Decimal("100"), 1)

    avg_ticket = Decimal("0.00")
    if converted_leads > 0 and total_revenue > 0:
        avg_ticket = round(total_revenue / Decimal(converted_leads), 2)

    return {
        "total_spent": total_spent,
        "total_revenue": total_revenue,
        "pipeline_value": pipeline_value,
        "total_leads": total_leads,
        "converted_leads": converted_leads,
        "active_pipeline_leads": active_pipeline_leads,
        "cac": cac,
        "roas": roas,
        "roi_percent": roi_percent,
        "cpl": cpl,
        "conversion_rate": conversion_rate,
        "avg_ticket": avg_ticket,
        "active_campaigns_count": campaigns.filter(status=Campaign.status.field.related_model if False else "ativa").count(),
    }


def get_funnel_summary(organization):
    """Return counts, values, and progression percentages for each funnel stage."""
    leads = Lead.objects.filter(organization=organization)
    total_leads = leads.count()

    stages = [
        (LeadStage.NOVO, "Novo Lead", "Captado via anúncio ou indicação"),
        (LeadStage.CONTATO, "Em Contato", "Qualificação e primeira sondagem"),
        (LeadStage.QUALIFICADO, "Reunião Marcada", "Consulta jurídica agendada"),
        (LeadStage.PROPOSTA, "Proposta Enviada", "Contrato e honorários sob análise"),
        (LeadStage.CONVERTIDO, "Contrato Fechado", "Cliente ativo do escritório"),
        (LeadStage.PERDIDO, "Desqualificado", "Não teve fit ou recusou"),
    ]

    funnel = []
    for stage_code, label, desc in stages:
        stage_leads = leads.filter(stage=stage_code)
        count = stage_leads.count()
        if stage_code == LeadStage.CONVERTIDO:
            val = stage_leads.aggregate(v=Sum("closed_value"))["v"] or Decimal("0.00")
        else:
            val = stage_leads.aggregate(v=Sum("estimated_value"))["v"] or Decimal("0.00")

        pct_of_total = round((Decimal(count) / Decimal(total_leads)) * Decimal("100"), 1) if total_leads else Decimal("0.0")

        funnel.append({
            "stage": stage_code,
            "label": label,
            "description": desc,
            "count": count,
            "value": val,
            "pct_of_total": pct_of_total,
        })

    return funnel


def get_channel_summary(organization):
    """Return performance and ROI per acquisition channel."""
    channels = []
    for code, label in MarketingChannel.choices:
        leads = Lead.objects.filter(organization=organization, channel=code)
        count = leads.count()
        converted = leads.filter(stage=LeadStage.CONVERTIDO).count()
        rev = leads.filter(stage=LeadStage.CONVERTIDO).aggregate(v=Sum("closed_value"))["v"] or Decimal("0.00")
        
        # Spent on this channel's campaigns
        spent = Campaign.objects.filter(organization=organization, channel=code).aggregate(v=Sum("spent"))["v"] or Decimal("0.00")

        conv_rate = round((Decimal(converted) / Decimal(count)) * Decimal("100"), 1) if count else Decimal("0.0")
        cac = round(spent / Decimal(converted), 2) if converted > 0 and spent > 0 else Decimal("0.00")
        roas = round(rev / spent, 2) if spent > 0 else Decimal("0.0")

        channels.append({
            "code": code,
            "label": label,
            "leads_count": count,
            "converted_count": converted,
            "spent": spent,
            "revenue": rev,
            "conversion_rate": conv_rate,
            "cac": cac,
            "roas": roas,
        })

    # Sort channels by revenue descending, then leads count
    channels.sort(key=lambda x: (x["revenue"], x["leads_count"]), reverse=True)
    return channels


def convert_lead_to_client(lead, actor=None, matter_title=None):
    """Converts a Lead into an active Contact and opens an automatic legal Matter."""
    from apps.legal.models import Contact, Matter
    from django.contrib.auth import get_user_model
    User = get_user_model()

    organization = lead.organization
    owner = actor
    if not owner or not isinstance(owner, User):
        owner = User.objects.filter(
            memberships__organization=organization,
            memberships__is_active=True
        ).first()

    # 1. Create Contact if not already existing
    contact = lead.converted_contact
    if not contact:
        contact = Contact.objects.filter(
            organization=organization,
            phone=lead.phone
        ).first()

        if not contact and lead.email:
            contact = Contact.objects.filter(
                organization=organization,
                email=lead.email
            ).first()

        if not contact:
            contact = Contact.objects.create(
                organization=organization,
                name=lead.name,
                phone=lead.phone,
                email=lead.email or "",
                notes=f"Origem: Marketing ({lead.get_channel_display()}).\n{lead.notes}",
                status=Contact.Status.ACTIVE,
            )

    # 2. Create Matter (Pasta Jurídica) for client
    matter = lead.converted_matter
    if not matter:
        title = matter_title or f"Pasta Jurídica · {lead.name} ({lead.legal_area.title()})"
        matter = Matter.objects.create(
            organization=organization,
            client=contact,
            title=title,
            area=lead.legal_area,
            owner=owner,
            nature=Matter.Nature.ADVISORY,
            status=Matter.Status.ACTIVE,
            description=f"Atendimento originado pelo marketing.\nCanal: {lead.get_channel_display()}.\nHonorários acordados: R$ {lead.closed_value or lead.estimated_value}",
        )

    # 3. Update Lead status
    lead.converted_contact = contact
    lead.converted_matter = matter
    lead.stage = LeadStage.CONVERTIDO
    if not lead.closed_value or lead.closed_value == 0:
        lead.closed_value = lead.estimated_value
    lead.converted_at = timezone.now()
    lead.save()

    return contact, matter
