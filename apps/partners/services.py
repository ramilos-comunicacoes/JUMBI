import hashlib
import hmac
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.models import AuditLog
from apps.office.models import Client, LegalCase

from .models import Partner, PartnerOpportunity, PartnerOpportunityEvent


OPPORTUNITY_TRANSITIONS = {
    PartnerOpportunity.Status.NEW: {
        PartnerOpportunity.Status.ANALYSIS,
        PartnerOpportunity.Status.DUPLICATE,
        PartnerOpportunity.Status.CANCELLED,
    },
    PartnerOpportunity.Status.ANALYSIS: {
        PartnerOpportunity.Status.CONTACTED,
        PartnerOpportunity.Status.DOCUMENTS_PENDING,
        PartnerOpportunity.Status.LOST,
        PartnerOpportunity.Status.DUPLICATE,
    },
    PartnerOpportunity.Status.CONTACTED: {
        PartnerOpportunity.Status.DOCUMENTS_PENDING,
        PartnerOpportunity.Status.WAITING,
        PartnerOpportunity.Status.CONSULTATION,
        PartnerOpportunity.Status.LOST,
    },
    PartnerOpportunity.Status.DOCUMENTS_PENDING: {
        PartnerOpportunity.Status.WAITING,
        PartnerOpportunity.Status.CONSULTATION,
        PartnerOpportunity.Status.LOST,
    },
    PartnerOpportunity.Status.WAITING: {
        PartnerOpportunity.Status.CONTACTED,
        PartnerOpportunity.Status.CONSULTATION,
        PartnerOpportunity.Status.LOST,
    },
    PartnerOpportunity.Status.CONSULTATION: {
        PartnerOpportunity.Status.PROPOSAL,
        PartnerOpportunity.Status.WAITING,
        PartnerOpportunity.Status.LOST,
    },
    PartnerOpportunity.Status.PROPOSAL: {
        PartnerOpportunity.Status.CONTRACT,
        PartnerOpportunity.Status.LOST,
    },
    PartnerOpportunity.Status.CONTRACT: {
        PartnerOpportunity.Status.CONVERTED,
        PartnerOpportunity.Status.LOST,
    },
    PartnerOpportunity.Status.CONVERTED: {PartnerOpportunity.Status.CASE_CREATED},
    PartnerOpportunity.Status.CASE_CREATED: set(),
    PartnerOpportunity.Status.CANCELLED: set(),
    PartnerOpportunity.Status.LOST: set(),
    PartnerOpportunity.Status.DUPLICATE: {
        PartnerOpportunity.Status.ANALYSIS,
        PartnerOpportunity.Status.CANCELLED,
    },
}


def normalize_digits(value):
    return re.sub(r"\D", "", value or "")


def protected_document(value):
    normalized = normalize_digits(value)
    if not normalized:
        return "", ""
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    visible = normalized[-4:]
    masked = f"•••.•••.•••-{visible}" if len(normalized) == 11 else f"••.•••.•••/••••-{visible}"
    return masked, digest


def normalized_phone(value):
    return normalize_digits(value)[-11:]


def possible_duplicates(*, organization, name, email="", phone="", document_hash="", exclude_pk=None):
    queryset = PartnerOpportunity.objects.filter(organization=organization)
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    duplicate_ids = set()
    if document_hash:
        duplicate_ids.update(queryset.filter(document_hash=document_hash).values_list("pk", flat=True))
    if email:
        duplicate_ids.update(queryset.filter(email__iexact=email.strip()).values_list("pk", flat=True))
    normalized = normalized_phone(phone)
    if normalized:
        for pk, stored_phone in queryset.exclude(phone="").values_list("pk", "phone"):
            if normalized_phone(stored_phone) == normalized:
                duplicate_ids.add(pk)
    compact_name = " ".join((name or "").split())
    if len(compact_name) >= 8:
        duplicate_ids.update(
            queryset.filter(interested_party_name__iexact=compact_name).values_list("pk", flat=True)
        )
    return sorted(duplicate_ids)


def active_partner_for_user(user):
    if not user.is_authenticated:
        return None
    return (
        Partner.objects.select_related("organization", "category")
        .filter(
            user=user,
            organization__status="active",
        )
        .exclude(status__in=[Partner.Status.REJECTED, Partner.Status.BLOCKED, Partner.Status.INACTIVE])
        .order_by("created_at")
        .first()
    )


@transaction.atomic
def change_opportunity_status(*, opportunity, target_status, actor, public_message="", internal_message=""):
    allowed = OPPORTUNITY_TRANSITIONS.get(opportunity.status, set())
    if target_status not in allowed:
        raise ValueError("Transição de etapa inválida para esta oportunidade.")
    previous = opportunity.status
    now = timezone.now()
    opportunity.status = target_status
    opportunity.partner_message = public_message
    if target_status == PartnerOpportunity.Status.CONTACTED and not opportunity.contacted_at:
        opportunity.contacted_at = now
    if target_status in {
        PartnerOpportunity.Status.CONVERTED,
        PartnerOpportunity.Status.CASE_CREATED,
    }:
        opportunity.converted_at = opportunity.converted_at or now
    if target_status in {
        PartnerOpportunity.Status.CANCELLED,
        PartnerOpportunity.Status.LOST,
        PartnerOpportunity.Status.DUPLICATE,
    }:
        opportunity.closed_at = now
    opportunity.save()
    PartnerOpportunityEvent.objects.create(
        opportunity=opportunity,
        actor=actor,
        from_status=previous,
        to_status=target_status,
        public_message=public_message,
        internal_message=internal_message,
    )
    AuditLog.objects.create(
        organization=opportunity.organization,
        actor=actor,
        action="partners.opportunity.status_changed",
        metadata={
            "id": str(opportunity.pk),
            "before": previous,
            "after": target_status,
        },
    )
    return opportunity


@transaction.atomic
def convert_opportunity(*, opportunity, actor):
    if opportunity.status in {
        PartnerOpportunity.Status.CANCELLED,
        PartnerOpportunity.Status.LOST,
        PartnerOpportunity.Status.DUPLICATE,
    }:
        raise ValueError("Esta oportunidade está encerrada e não pode ser convertida.")
    client = (
        Client.objects.filter(organization=opportunity.organization, email__iexact=opportunity.email).first()
        if opportunity.email
        else None
    )
    if client is None and opportunity.phone:
        client = Client.objects.filter(
            organization=opportunity.organization,
            phone=opportunity.phone,
        ).first()
    if client is None:
        client = Client.objects.create(
            organization=opportunity.organization,
            name=opportunity.interested_party_name,
            email=opportunity.email,
            phone=opportunity.phone,
        )
    legal_case = LegalCase.objects.create(
        organization=opportunity.organization,
        client=client,
        practice_area=opportunity.practice_area,
        matter_type=opportunity.matter_type,
        title=f"Atendimento · {opportunity.interested_party_name}",
        description=opportunity.description,
        nature=LegalCase.Nature.ADVISORY,
        stage=LegalCase.Stage.INTAKE,
        status=LegalCase.Status.INTAKE,
    )
    previous = opportunity.status
    opportunity.converted_client = client
    opportunity.converted_case = legal_case
    opportunity.status = PartnerOpportunity.Status.CASE_CREATED
    opportunity.converted_at = timezone.now()
    opportunity.save()
    PartnerOpportunityEvent.objects.create(
        opportunity=opportunity,
        actor=actor,
        from_status=previous,
        to_status=PartnerOpportunity.Status.CASE_CREATED,
        public_message="A oportunidade foi acolhida pelo escritório e seguirá no atendimento interno.",
        internal_message=f"Cliente #{client.pk} e caso #{legal_case.pk} criados.",
    )
    AuditLog.objects.create(
        organization=opportunity.organization,
        actor=actor,
        action="partners.opportunity.converted",
        metadata={
            "id": str(opportunity.pk),
            "client_id": str(client.pk),
            "case_id": str(legal_case.pk),
        },
    )
    return client, legal_case
