import hashlib

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404
from django.utils import timezone

from apps.billing.services import require_access
from apps.core.models import Membership
from apps.legal.models import DocumentVersion
from apps.legal.services import audit, visible_matters
from .models import ClientAccess, DocumentReview, PortalMessage, Publication, ReviewDecision


def membership_for(user, organization):
    if not user.is_authenticated or not user.is_active or organization.status != "active":
        return None
    return Membership.objects.filter(user=user, organization=organization, is_active=True).first()


def authorize_staff(actor, organization, *, manager=False, write=True):
    member = membership_for(actor, organization)
    roles = {"owner", "manager"} if manager else {"owner", "manager", "operator"}
    if not member or member.role not in roles:
        raise PermissionDenied("Seu perfil não permite gerenciar publicações e revisões.")
    if write:
        require_access(organization, advanced=True)
    return member


def authorized_versions(actor, organization):
    member = membership_for(actor, organization)
    if not member or member.role not in {"owner", "manager", "operator"}:
        return DocumentVersion.objects.none()
    return DocumentVersion.objects.filter(organization=organization, document__matter__in=visible_matters(actor, organization))


def visible_reviews(actor, organization):
    return DocumentReview.objects.filter(organization=organization, version__in=authorized_versions(actor, organization))


def visible_publications(actor, organization, *, include_revoked=False):
    member = membership_for(actor, organization)
    if not member:
        return Publication.objects.none()
    publications = Publication.objects.filter(organization=organization)
    if member.role == "client":
        return publications.filter(
            access__membership=member, access__contact_id=F("review__version__document__matter__client_id"),
            access__revoked_at__isnull=True, revoked_at__isnull=True,
            review__checksum=F("review__version__checksum"),
            review__decision__outcome=ReviewDecision.Outcome.APPROVED,
        ).filter(Q(review__version__document__matter__confidential=False) |
                 Q(review__version__document__matter__members=actor) |
                 Q(review__version__document__matter__owner=actor)).distinct()
    if member.role not in {"owner", "manager", "operator"}:
        return publications.none()
    publications = publications.filter(review__in=visible_reviews(actor, organization))
    return publications if include_revoked else publications.filter(revoked_at__isnull=True, access__revoked_at__isnull=True)


def visible_accesses(actor, organization):
    member = membership_for(actor, organization)
    if not member or member.role not in {"owner", "manager"}:
        return ClientAccess.objects.none()
    # Contacts may only be selected if a currently accessible case belongs to them.
    return ClientAccess.objects.filter(organization=organization, contact_id__in=visible_matters(actor, organization).values("client_id"))


def scoped_portal_queryset(actor, organization, model):
    """Internal export/audit scope, independent of plan, never broad client scope."""
    member = membership_for(actor, organization)
    if not member or member.role == "client":
        return model.objects.none()
    if model is ClientAccess:
        return visible_accesses(actor, organization)
    if model is DocumentReview:
        return visible_reviews(actor, organization)
    if model is ReviewDecision:
        return model.objects.filter(organization=organization, review__in=visible_reviews(actor, organization))
    if model is Publication:
        return visible_publications(actor, organization, include_revoked=True)
    if model is PortalMessage:
        return model.objects.filter(organization=organization, publication__in=visible_publications(actor, organization, include_revoked=True))
    return model.objects.none()


def verified_source(version, checksum=None):
    """Check bytes before returning a stream; never expose a corrupted publication."""
    expected = checksum or version.checksum
    if version.checksum != expected:
        raise Http404("A integridade da versão não pôde ser confirmada.")
    try:
        source = version.file.open("rb")
        digest = hashlib.sha256()
        for chunk in source.chunks():
            digest.update(chunk)
        if digest.hexdigest() != expected:
            source.close()
            raise Http404("A integridade do arquivo não pôde ser confirmada.")
        source.seek(0)
        return source
    except (FileNotFoundError, OSError):
        raise Http404("O arquivo não está disponível. Contate o escritório.") from None


@transaction.atomic
def grant_access(*, actor, organization, membership, contact):
    authorize_staff(actor, organization, manager=True)
    membership = Membership.objects.select_for_update().get(pk=membership.pk)
    if membership.organization_id != organization.pk or contact.organization_id != organization.pk:
        raise PermissionDenied("O vínculo pertence a outro escritório.")
    if not visible_matters(actor, organization).filter(client=contact).exists():
        raise PermissionDenied("O contato precisa estar vinculado a uma pasta acessível.")
    if membership.role != "client" or not membership.is_active or not membership.user.is_active:
        raise ValidationError("Selecione um membro ativo com perfil Cliente.")
    existing = ClientAccess.objects.filter(organization=organization, membership=membership, contact=contact, revoked_at__isnull=True).first()
    if existing:
        return existing
    access = ClientAccess.objects.create(organization=organization, membership=membership, contact=contact, created_by=actor)
    audit(organization=organization, actor=actor, action="portal.access_granted", obj=access, description="Vínculo explícito de conta de cliente com contato; nenhum documento publicado automaticamente.")
    return access


@transaction.atomic
def request_review(*, actor, organization, version, reviewer, note):
    authorize_staff(actor, organization)
    version = DocumentVersion.objects.select_for_update().get(pk=version.pk, organization=organization)
    if not authorized_versions(actor, organization).filter(pk=version.pk).exists():
        raise PermissionDenied("Você não tem acesso à pasta deste documento.")
    authorize_staff(reviewer, organization, manager=True, write=False)
    if not authorized_versions(reviewer, organization).filter(pk=version.pk).exists():
        raise ValidationError("A pessoa revisora precisa ter acesso à pasta, inclusive quando sigilosa.")
    with verified_source(version):
        pass
    review = DocumentReview.objects.create(organization=organization, version=version, checksum=version.checksum, requested_by=actor, reviewer=reviewer, note=note.strip())
    audit(organization=organization, actor=actor, action="portal.review_requested", obj=review, description=f"Solicitada revisão da versão {version.number}, SHA-256 {version.checksum}.")
    return review


@transaction.atomic
def decide_review(*, actor, review, outcome, note):
    review = DocumentReview.objects.select_for_update().get(pk=review.pk, organization_id=review.organization_id)
    authorize_staff(actor, review.organization, manager=True)
    if review.reviewer_id != actor.pk or not visible_reviews(actor, review.organization).filter(pk=review.pk).exists():
        raise PermissionDenied("Somente a pessoa designada, com acesso atual à pasta, pode decidir.")
    if ReviewDecision.objects.filter(review=review).exists():
        raise ValidationError("Esta revisão já possui uma decisão. Solicite uma nova revisão quando necessário.")
    if review.reviewer_id in {review.requested_by_id, review.version.uploaded_by_id}:
        raise ValidationError("A revisão deve ser independente.")
    with verified_source(review.version, review.checksum):
        pass
    decision = ReviewDecision.objects.create(organization=review.organization, review=review, actor=actor, outcome=outcome, note=note.strip())
    audit(organization=review.organization, actor=actor, action="portal.review_decided", obj=decision, description=f"{decision.get_outcome_display()}: {note.strip()}")
    return decision


@transaction.atomic
def publish_version(*, actor, review, access, title, note=""):
    review = DocumentReview.objects.select_for_update().get(pk=review.pk, organization_id=review.organization_id)
    authorize_staff(actor, review.organization, manager=True)
    if not visible_reviews(actor, review.organization).filter(pk=review.pk).exists():
        raise PermissionDenied("Você não tem acesso à pasta deste documento.")
    access = ClientAccess.objects.select_for_update().get(pk=access.pk)
    if access.organization_id != review.organization_id:
        raise PermissionDenied("O destinatário pertence a outro escritório.")
    member = membership_for(access.membership.user, review.organization)
    if not member or member.pk != access.membership_id or member.role != "client" or access.revoked_at:
        raise ValidationError("O acesso do destinatário não está ativo.")
    matter = review.version.document.matter
    if matter.confidential and matter.owner_id != member.user_id and not matter.members.filter(pk=member.user_id).exists():
        raise ValidationError("A pasta é sigilosa. Inclua explicitamente o cliente entre as pessoas autorizadas à pasta antes de publicar.")
    with verified_source(review.version, review.checksum):
        pass
    existing = Publication.objects.filter(review=review, access=access, revoked_at__isnull=True).first()
    if existing:
        return existing
    publication = Publication.objects.create(organization=review.organization, review=review, access=access, title=title.strip(), note=note.strip(), published_by=actor)
    audit(organization=review.organization, actor=actor, action="portal.document_published", obj=publication, description=f"Versão {review.version.number} disponibilizada explicitamente à conta #{member.pk}.")
    return publication


@transaction.atomic
def revoke(*, actor, record, reason):
    record = type(record).objects.select_for_update().get(pk=record.pk, organization_id=record.organization_id)
    authorize_staff(actor, record.organization, manager=True, write=False)
    # Revocation is a security action and remains available after subscription expiry.
    allowed = visible_accesses(actor, record.organization) if isinstance(record, ClientAccess) else visible_publications(actor, record.organization, include_revoked=True)
    if not allowed.filter(pk=record.pk).exists():
        raise PermissionDenied("Você não tem acesso a este vínculo.")
    if record.revoked_at:
        return record
    record.revoked_at, record.revoked_by, record.revoke_reason = timezone.now(), actor, reason.strip()
    record._allow_revoke = True
    record.save(update_fields=["revoked_at", "revoked_by", "revoke_reason"])
    audit(organization=record.organization, actor=actor, action="portal.access_revoked" if isinstance(record, ClientAccess) else "portal.publication_revoked", obj=record, description=reason.strip())
    return record


@transaction.atomic
def send_message(*, actor, publication, body):
    publication = Publication.objects.select_for_update().get(pk=publication.pk, organization_id=publication.organization_id)
    # Serialize against both publication and whole-contact revocation. A staff
    # member's history access alone is not permission to append a client thread.
    access = ClientAccess.objects.select_for_update().get(pk=publication.access_id)
    require_access(publication.organization, advanced=True)
    if not visible_publications(actor, publication.organization).filter(pk=publication.pk).exists():
        raise PermissionDenied("Esta publicação não está disponível para mensagens.")
    if access.membership.role != "client" or not visible_publications(access.membership.user, publication.organization).filter(pk=publication.pk).exists():
        raise PermissionDenied("O destinatário não possui mais acesso a esta publicação.")
    message = PortalMessage.objects.create(organization=publication.organization, publication=publication, actor=actor, body=body.strip())
    audit(organization=publication.organization, actor=actor, action="portal.message_sent", obj=message, description="Mensagem registrada na conversa da publicação.")
    return message
