from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import AuditLog, Organization
from apps.core.services import require_business_organization, require_permission

from .forms import (
    PartnerCampaignForm,
    PartnerCategoryForm,
    PartnerMaterialForm,
    PartnerNetworkSettingsForm,
    PartnerOpportunityForm,
    PartnerProfileForm,
    PartnerProvisionForm,
    PartnerTermsAcceptanceForm,
)
from .models import (
    Partner,
    PartnerCampaign,
    PartnerCategory,
    PartnerMaterial,
    PartnerNetworkSettings,
    PartnerOpportunity,
    PartnerOpportunityEvent,
)
from .services import (
    OPPORTUNITY_TRANSITIONS,
    active_partner_for_user,
    change_opportunity_status,
    convert_opportunity,
)


DEFAULT_PARTNER_CATEGORIES = (
    ("Contabilidade", PartnerCategory.Kind.BUSINESS),
    ("Correspondência jurídica", PartnerCategory.Kind.LEGAL_CORRESPONDENT),
    ("Imobiliária", PartnerCategory.Kind.BUSINESS),
    ("Clínica ou profissional da saúde", PartnerCategory.Kind.BUSINESS),
    ("Sindicato, associação ou cooperativa", PartnerCategory.Kind.COMMUNITY),
)


def _network_for(organization):
    network, _ = PartnerNetworkSettings.objects.get_or_create(organization=organization)
    if not PartnerCategory.objects.filter(organization=organization).exists():
        PartnerCategory.objects.bulk_create(
            [
                PartnerCategory(
                    organization=organization,
                    name=name,
                    kind=kind,
                    sort_order=index * 10,
                )
                for index, (name, kind) in enumerate(DEFAULT_PARTNER_CATEGORIES, start=1)
            ]
        )
    return network


def partner_workspace_context(request, organization):
    network = _network_for(organization)
    network_form = PartnerNetworkSettingsForm(instance=network, prefix="network")
    category_form = PartnerCategoryForm(prefix="category")
    partner_form = PartnerProvisionForm(prefix="partner", organization=organization)
    campaign_form = PartnerCampaignForm(prefix="campaign", organization=organization)
    material_form = PartnerMaterialForm(prefix="material", organization=organization)
    saved_message = ""

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "partner_network":
            require_permission(request.user, "partners.manage_network", organization)
            network_form = PartnerNetworkSettingsForm(request.POST, instance=network, prefix="network")
            if network_form.is_valid():
                network_form.save_with_actor(request.user)
                AuditLog.objects.create(
                    organization=organization,
                    actor=request.user,
                    action="partners.network.updated",
                    metadata={"enabled": network_form.cleaned_data["is_enabled"]},
                )
                saved_message = "Configurações da Rede de Parceiros atualizadas."
        elif action == "partner_category":
            require_permission(request.user, "partners.manage_network", organization)
            category_form = PartnerCategoryForm(request.POST, prefix="category")
            if category_form.is_valid():
                category = category_form.save(commit=False)
                category.organization = organization
                category.save()
                AuditLog.objects.create(
                    organization=organization,
                    actor=request.user,
                    action="partners.category.created",
                    metadata={"id": str(category.pk)},
                )
                saved_message = "Categoria de parceiro criada."
        elif action == "partner":
            require_permission(request.user, "partners.manage_partners", organization)
            partner_form = PartnerProvisionForm(
                request.POST,
                prefix="partner",
                organization=organization,
            )
            if partner_form.is_valid():
                partner = partner_form.save(request.user)
                AuditLog.objects.create(
                    organization=organization,
                    actor=request.user,
                    action="partners.partner.created",
                    metadata={"id": str(partner.pk), "status": partner.status},
                )
                saved_message = "Parceiro cadastrado. O acesso ficará limitado ao portal da rede."
        elif action == "partner_campaign":
            require_permission(request.user, "partners.manage_campaigns", organization)
            campaign_form = PartnerCampaignForm(
                request.POST,
                prefix="campaign",
                organization=organization,
            )
            if campaign_form.is_valid():
                campaign = campaign_form.save(commit=False)
                campaign.created_by = request.user
                campaign.save()
                campaign_form.save_m2m()
                AuditLog.objects.create(
                    organization=organization,
                    actor=request.user,
                    action="partners.campaign.created",
                    metadata={"id": str(campaign.pk), "status": campaign.status},
                )
                saved_message = "Campanha criada na Rede de Parceiros."
        elif action == "partner_material":
            require_permission(request.user, "partners.manage_campaigns", organization)
            material_form = PartnerMaterialForm(
                request.POST,
                prefix="material",
                organization=organization,
            )
            if material_form.is_valid():
                material = material_form.save()
                AuditLog.objects.create(
                    organization=organization,
                    actor=request.user,
                    action="partners.material.created",
                    metadata={"id": str(material.pk)},
                )
                saved_message = "Material publicado para os parceiros."

    opportunities = (
        PartnerOpportunity.objects.filter(organization=organization)
        .select_related("partner", "practice_area", "campaign", "converted_client", "converted_case")
        .prefetch_related("events")
    )
    for opportunity in opportunities:
        allowed = OPPORTUNITY_TRANSITIONS.get(opportunity.status, set())
        opportunity.allowed_transitions = [
            choice for choice in PartnerOpportunity.Status.choices if choice[0] in allowed
        ]
    partners = (
        Partner.objects.filter(organization=organization)
        .select_related("category", "user")
        .annotate(
            opportunity_count=Count("opportunities"),
            conversion_count=Count(
                "opportunities",
                filter=Q(
                    opportunities__status__in=[
                        PartnerOpportunity.Status.CONVERTED,
                        PartnerOpportunity.Status.CASE_CREATED,
                    ]
                ),
            ),
        )
    )
    total_opportunities = opportunities.count()
    converted_count = opportunities.filter(
        status__in=[
            PartnerOpportunity.Status.CONVERTED,
            PartnerOpportunity.Status.CASE_CREATED,
        ]
    ).count()
    context = {
        "partner_network": network,
        "partner_network_form": network_form,
        "partner_category_form": category_form,
        "partner_form": partner_form,
        "partner_campaign_form": campaign_form,
        "partner_material_form": material_form,
        "partners": partners,
        "partner_categories": PartnerCategory.objects.filter(organization=organization),
        "partner_campaigns": PartnerCampaign.objects.filter(organization=organization).select_related("practice_area"),
        "partner_materials": PartnerMaterial.objects.filter(organization=organization).select_related("campaign"),
        "partner_opportunities": opportunities,
        "partner_status_choices": Partner.Status.choices,
        "opportunity_status_choices": PartnerOpportunity.Status.choices,
        "opportunity_transitions": OPPORTUNITY_TRANSITIONS,
        "partners_active_count": partners.filter(status=Partner.Status.APPROVED).count(),
        "partners_pending_count": partners.filter(status=Partner.Status.PENDING).count(),
        "partner_opportunity_count": total_opportunities,
        "partner_conversion_count": converted_count,
        "partner_conversion_rate": round((converted_count / total_opportunities) * 100) if total_opportunities else 0,
        "partner_workspace_saved_message": saved_message,
    }
    return context


def _partner_for_request(request):
    partner = active_partner_for_user(request.user)
    if partner is None:
        raise PermissionDenied("Sua conta não possui acesso ativo a um portal de parceiros.")
    return partner


@login_required
def portal(request):
    partner = _partner_for_request(request)
    network = PartnerNetworkSettings.objects.filter(organization=partner.organization).first()
    opportunity_form = PartnerOpportunityForm(prefix="opportunity", partner=partner)
    profile_form = PartnerProfileForm(instance=partner, prefix="profile")
    terms_form = PartnerTermsAcceptanceForm(prefix="terms")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "opportunity":
            if (
                partner.status != Partner.Status.APPROVED
                or network is None
                or not network.is_enabled
                or not network.compliance_acknowledged
                or not partner.terms_accepted_at
                or not partner.privacy_accepted_at
            ):
                raise PermissionDenied("O envio de oportunidades ainda não está habilitado para este acesso.")
            opportunity_form = PartnerOpportunityForm(
                request.POST,
                prefix="opportunity",
                partner=partner,
            )
            if opportunity_form.is_valid():
                with transaction.atomic():
                    opportunity, duplicate_ids = opportunity_form.save_for_partner(request=request)
                    PartnerOpportunityEvent.objects.create(
                        opportunity=opportunity,
                        actor=request.user,
                        to_status=opportunity.status,
                        public_message="Oportunidade registrada no portal.",
                        internal_message=(
                            f"Possível relação com registros: {duplicate_ids}"
                            if duplicate_ids
                            else "Cadastro inicial pelo parceiro."
                        ),
                    )
                    AuditLog.objects.create(
                        organization=partner.organization,
                        actor=request.user,
                        action="partners.opportunity.created",
                        metadata={
                            "id": str(opportunity.pk),
                            "possible_duplicate": bool(duplicate_ids),
                        },
                    )
                messages.success(
                    request,
                    "Oportunidade enviada com segurança. O escritório já pode iniciar a triagem.",
                )
                return redirect("partners:portal")
        elif action == "profile":
            profile_form = PartnerProfileForm(request.POST, instance=partner, prefix="profile")
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Seus dados de contato foram atualizados.")
                return redirect("partners:portal")
        elif action == "accept_terms":
            terms_form = PartnerTermsAcceptanceForm(request.POST, prefix="terms")
            if terms_form.is_valid():
                now = timezone.now()
                partner.terms_accepted_at = now
                partner.privacy_accepted_at = now
                partner.save(update_fields=["terms_accepted_at", "privacy_accepted_at", "updated_at"])
                AuditLog.objects.create(
                    organization=partner.organization,
                    actor=request.user,
                    action="partners.partner.terms_accepted",
                    metadata={
                        "partner_id": str(partner.pk),
                        "privacy_version": network.privacy_notice_version if network else "",
                    },
                )
                messages.success(request, "Termos e aviso de privacidade aceitos.")
                return redirect("partners:portal")

    Partner.objects.filter(pk=partner.pk).update(last_access_at=timezone.now())
    today = timezone.localdate()
    campaigns = PartnerCampaign.objects.filter(
        organization=partner.organization,
        status=PartnerCampaign.Status.ACTIVE,
    ).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=today),
        Q(ends_at__isnull=True) | Q(ends_at__gte=today),
    ).annotate(
        total_submissions=Count("opportunities", distinct=True),
        partner_submissions=Count(
            "opportunities",
            filter=Q(opportunities__partner=partner),
            distinct=True,
        ),
    ).filter(
        Q(opportunity_limit__isnull=True) | Q(total_submissions__lt=F("opportunity_limit")),
        Q(per_partner_limit__isnull=True) | Q(partner_submissions__lt=F("per_partner_limit")),
    )
    if partner.category_id:
        campaigns = campaigns.filter(
            Q(eligible_categories__isnull=True) | Q(eligible_categories=partner.category)
        ).distinct()
    else:
        campaigns = campaigns.filter(eligible_categories__isnull=True)
    materials = PartnerMaterial.objects.filter(
        organization=partner.organization,
        is_active=True,
    ).filter(Q(campaign__isnull=True) | Q(campaign__in=campaigns))
    context = {
        "partner": partner,
        "partner_network": network,
        "opportunity_form": opportunity_form,
        "profile_form": profile_form,
        "terms_form": terms_form,
        "opportunities": PartnerOpportunity.objects.filter(partner=partner).select_related(
            "practice_area",
            "campaign",
        ).prefetch_related("events"),
        "opportunities_in_progress_count": PartnerOpportunity.objects.filter(
            partner=partner,
            status__in=[
                PartnerOpportunity.Status.ANALYSIS,
                PartnerOpportunity.Status.CONTACTED,
                PartnerOpportunity.Status.DOCUMENTS_PENDING,
                PartnerOpportunity.Status.WAITING,
                PartnerOpportunity.Status.CONSULTATION,
                PartnerOpportunity.Status.PROPOSAL,
                PartnerOpportunity.Status.CONTRACT,
            ],
        ).count(),
        "campaigns": campaigns.select_related("practice_area"),
        "materials": materials.select_related("campaign"),
    }
    return render(request, "partners/portal.html", context)


@login_required
@require_POST
def partner_status(request, pk):
    organization = require_business_organization(request, Organization.BusinessType.OFFICE)
    require_permission(request.user, "partners.manage_partners", organization)
    partner = Partner.objects.filter(organization=organization, pk=pk).first()
    if partner is None:
        return HttpResponseBadRequest("Parceiro não encontrado nesta organização.")
    target = request.POST.get("status")
    if target not in dict(Partner.Status.choices):
        return HttpResponseBadRequest("Status de parceiro inválido.")
    before = partner.status
    partner.status = target
    if target == Partner.Status.APPROVED:
        partner.approved_by = request.user
        partner.approved_at = timezone.now()
    partner.save()
    AuditLog.objects.create(
        organization=organization,
        actor=request.user,
        action="partners.partner.status_changed",
        metadata={"id": str(partner.pk), "before": before, "after": target},
    )
    messages.success(request, "Status do parceiro atualizado.")
    return redirect("office:section", section="partners")


@login_required
@require_POST
def opportunity_status(request, pk):
    organization = require_business_organization(request, Organization.BusinessType.OFFICE)
    require_permission(request.user, "partners.manage_opportunities", organization)
    opportunity = PartnerOpportunity.objects.filter(organization=organization, pk=pk).first()
    if opportunity is None:
        return HttpResponseBadRequest("Oportunidade não encontrada nesta organização.")
    try:
        change_opportunity_status(
            opportunity=opportunity,
            target_status=request.POST.get("status", ""),
            actor=request.user,
            public_message=request.POST.get("public_message", "")[:1000],
            internal_message=request.POST.get("internal_message", "")[:2000],
        )
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    messages.success(request, "Etapa da oportunidade atualizada e registrada na auditoria.")
    return redirect("office:section", section="partners")


@login_required
@require_POST
def opportunity_convert(request, pk):
    organization = require_business_organization(request, Organization.BusinessType.OFFICE)
    require_permission(request.user, "partners.manage_opportunities", organization)
    opportunity = PartnerOpportunity.objects.filter(organization=organization, pk=pk).first()
    if opportunity is None:
        return HttpResponseBadRequest("Oportunidade não encontrada nesta organização.")
    try:
        client, legal_case = convert_opportunity(opportunity=opportunity, actor=request.user)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    messages.success(
        request,
        f"Oportunidade convertida em cliente e caso jurídico #{legal_case.pk}.",
    )
    return redirect("office:section", section="partners")
