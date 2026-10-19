from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.services import member_has_module
from .models import Campaign, Lead, LeadStage, MarketingChannel, MarketingExpense
from .forms import CampaignForm, LeadForm, LeadConvertForm, MarketingExpenseForm
from .services import (
    calculate_marketing_kpis,
    get_funnel_summary,
    get_channel_summary,
    convert_lead_to_client,
)


def _check_marketing_access(request):
    membership = getattr(request, "membership", None)
    return member_has_module(membership, "marketing")


@login_required
def dashboard(request):
    organization = getattr(request, "organization", None)
    if not organization or not _check_marketing_access(request):
        messages.error(request, "Você não tem permissão para acessar o módulo de Marketing.")
        return redirect("legal:dashboard")

    kpis = calculate_marketing_kpis(organization)
    funnel = get_funnel_summary(organization)
    channels = get_channel_summary(organization)
    recent_leads = Lead.objects.filter(organization=organization).select_related("campaign")[:8]
    active_campaigns = Campaign.objects.filter(organization=organization)[:6]

    context = {
        "page_title": "Marketing & Captação",
        "active_tab": "dashboard",
        "kpis": kpis,
        "funnel": funnel,
        "channels": channels,
        "recent_leads": recent_leads,
        "active_campaigns": active_campaigns,
    }

    if request.headers.get("HX-Request") and request.GET.get("partial") == "kpis":
        return render(request, "marketing/includes/kpi_cards.html", context)

    return render(request, "marketing/dashboard.html", context)


@login_required
def leads_kanban(request):
    organization = getattr(request, "organization", None)
    if not organization or not _check_marketing_access(request):
        return redirect("legal:dashboard")

    q = request.GET.get("q", "").strip()
    channel_filter = request.GET.get("channel", "").strip()
    campaign_filter = request.GET.get("campaign", "").strip()

    qs = Lead.objects.filter(organization=organization).select_related("campaign", "assigned_to")
    if q:
        qs = qs.filter(name__icontains=q) | qs.filter(phone__icontains=q) | qs.filter(email__icontains=q)
    if channel_filter:
        qs = qs.filter(channel=channel_filter)
    if campaign_filter:
        qs = qs.filter(campaign_id=campaign_filter)

    leads_by_stage = {
        LeadStage.NOVO: [],
        LeadStage.CONTATO: [],
        LeadStage.QUALIFICADO: [],
        LeadStage.PROPOSTA: [],
        LeadStage.CONVERTIDO: [],
        LeadStage.PERDIDO: [],
    }

    for lead in qs:
        if lead.stage in leads_by_stage:
            leads_by_stage[lead.stage].append(lead)

    context = {
        "page_title": "Funil & Pipeline de Leads",
        "active_tab": "kanban",
        "leads_by_stage": leads_by_stage,
        "stages": LeadStage.choices,
        "q": q,
        "channel_filter": channel_filter,
        "campaign_filter": campaign_filter,
        "channels": MarketingChannel.choices,
        "campaigns": Campaign.objects.filter(organization=organization),
        "total_filtered_count": qs.count(),
    }

    if request.headers.get("HX-Request"):
        return render(request, "marketing/includes/kanban_board.html", context)

    return render(request, "marketing/leads_kanban.html", context)


@login_required
def lead_create(request):
    organization = getattr(request, "organization", None)
    if not organization or not _check_marketing_access(request):
        return redirect("legal:dashboard")

    if request.method == "POST":
        form = LeadForm(request.POST, organization=organization)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.organization = organization
            lead.save()
            messages.success(request, f"Lead '{lead.name}' cadastrado com sucesso!")
            if request.headers.get("HX-Request"):
                return HttpResponse(headers={"HX-Redirect": reverse("marketing:leads_kanban")})
            return redirect("marketing:leads_kanban")
    else:
        initial = {}
        if request.GET.get("channel"):
            initial["channel"] = request.GET.get("channel")
        if request.GET.get("campaign"):
            initial["campaign"] = request.GET.get("campaign")
        form = LeadForm(organization=organization, initial=initial)

    return render(request, "marketing/lead_form.html", {
        "page_title": "Novo Lead",
        "form": form,
        "is_create": True,
    })


@login_required
def lead_edit(request, lead_id):
    organization = getattr(request, "organization", None)
    lead = get_object_or_404(Lead, id=lead_id, organization=organization)

    if request.method == "POST":
        form = LeadForm(request.POST, instance=lead, organization=organization)
        if form.is_valid():
            lead = form.save()
            messages.success(request, f"Lead '{lead.name}' atualizado.")
            return redirect("marketing:leads_kanban")
    else:
        form = LeadForm(instance=lead, organization=organization)

    return render(request, "marketing/lead_form.html", {
        "page_title": f"Editar Lead · {lead.name}",
        "form": form,
        "lead": lead,
        "is_create": False,
    })


@login_required
@require_POST
def lead_update_stage(request, lead_id):
    """Fast HTMX endpoint to transition a lead's stage in the Kanban board."""
    organization = getattr(request, "organization", None)
    lead = get_object_or_404(Lead, id=lead_id, organization=organization)
    new_stage = request.POST.get("stage")

    if new_stage in LeadStage.values:
        lead.stage = new_stage
        if new_stage == LeadStage.CONVERTIDO and not lead.converted_at:
            convert_lead_to_client(lead, actor=request.user)
        else:
            lead.save()

    if request.headers.get("HX-Request"):
        return render(request, "marketing/includes/lead_card.html", {"lead": lead})

    return redirect("marketing:leads_kanban")


@login_required
def lead_convert_view(request, lead_id):
    """Direct conversion of a lead into a Contact and new Matter."""
    organization = getattr(request, "organization", None)
    lead = get_object_or_404(Lead, id=lead_id, organization=organization)

    if request.method == "POST":
        form = LeadConvertForm(request.POST)
        if form.is_valid():
            matter_title = form.cleaned_data.get("matter_title")
            closed_value = form.cleaned_data.get("closed_value")
            if closed_value:
                lead.closed_value = closed_value
            contact, matter = convert_lead_to_client(lead, actor=request.user, matter_title=matter_title)
            messages.success(
                request,
                f"Sucesso! Cliente '{contact.full_name}' e Pasta Jurídica '{matter.folder_code or matter.title}' criados automaticamente."
            )
            return redirect("legal:matter_detail", pk=matter.pk)
    else:
        form = LeadConvertForm(initial={
            "matter_title": f"Pasta Jurídica · {lead.name} ({lead.legal_area.title()})",
            "closed_value": lead.closed_value or lead.estimated_value,
        })

    return render(request, "marketing/lead_convert.html", {
        "page_title": f"Converter Lead em Cliente · {lead.name}",
        "lead": lead,
        "form": form,
    })


@login_required
def campaign_list(request):
    organization = getattr(request, "organization", None)
    if not organization or not _check_marketing_access(request):
        return redirect("legal:dashboard")

    campaigns = Campaign.objects.filter(organization=organization).prefetch_related("leads")
    return render(request, "marketing/campaign_list.html", {
        "page_title": "Campanhas de Marketing",
        "active_tab": "campaigns",
        "campaigns": campaigns,
    })


@login_required
def campaign_create(request):
    organization = getattr(request, "organization", None)
    if not organization or not _check_marketing_access(request):
        return redirect("legal:dashboard")

    if request.method == "POST":
        form = CampaignForm(request.POST)
        if form.is_valid():
            camp = form.save(commit=False)
            camp.organization = organization
            camp.created_by = request.user
            camp.save()
            messages.success(request, f"Campanha '{camp.name}' criada com sucesso!")
            return redirect("marketing:campaign_list")
    else:
        form = CampaignForm()

    return render(request, "marketing/campaign_form.html", {
        "page_title": "Nova Campanha de Marketing",
        "form": form,
        "is_create": True,
    })


@login_required
def campaign_edit(request, campaign_id):
    organization = getattr(request, "organization", None)
    camp = get_object_or_404(Campaign, id=campaign_id, organization=organization)

    if request.method == "POST":
        form = CampaignForm(request.POST, instance=camp)
        if form.is_valid():
            camp = form.save()
            messages.success(request, f"Campanha '{camp.name}' atualizada.")
            return redirect("marketing:campaign_list")
    else:
        form = CampaignForm(instance=camp)

    return render(request, "marketing/campaign_form.html", {
        "page_title": f"Editar Campanha · {camp.name}",
        "form": form,
        "campaign": camp,
        "is_create": False,
    })


@login_required
def utm_builder(request):
    """Tool for generating tracking links with UTM parameters."""
    organization = getattr(request, "organization", None)
    if not organization or not _check_marketing_access(request):
        return redirect("legal:dashboard")

    campaigns = Campaign.objects.filter(organization=organization)
    return render(request, "marketing/utm_builder.html", {
        "page_title": "Gerador de Links UTM & Rastreamento",
        "active_tab": "utm",
        "campaigns": campaigns,
    })


@login_required
def expense_list(request):
    organization = getattr(request, "organization", None)
    if not organization or not _check_marketing_access(request):
        return redirect("legal:dashboard")

    if request.method == "POST":
        form = MarketingExpenseForm(request.POST, organization=organization)
        if form.is_valid():
            exp = form.save(commit=False)
            exp.organization = organization
            exp.save()
            messages.success(request, "Despesa de marketing registrada.")
            return redirect("marketing:expense_list")
    else:
        form = MarketingExpenseForm(organization=organization)

    expenses = MarketingExpense.objects.filter(organization=organization).select_related("campaign")
    return render(request, "marketing/expense_list.html", {
        "page_title": "Despesas & Custos de Marketing",
        "active_tab": "expenses",
        "form": form,
        "expenses": expenses,
    })
