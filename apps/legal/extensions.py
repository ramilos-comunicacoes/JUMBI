"""Export and audit scopes shared by the workspace's additional modules."""
from django.db.models import Q

from apps.fees.models import FeePlan, FeeInstallment
from apps.portal.models import ClientAccess, DocumentReview, ReviewDecision, Publication, PortalMessage
from apps.routines.models import RoutineTemplate, RoutineApplication, MatterChecklist, MatterComment


EXTRA_EXPORT_FIELDS = {
    RoutineTemplate: ['title', 'description', 'niches', 'tasks', 'checklist', 'documents', 'is_active', 'version', 'created_by_id', 'created_at', 'updated_at'],
    RoutineApplication: ['matter_id', 'template_id', 'template_version', 'snapshot', 'task_due_date', 'task_ids', 'created_by_id', 'created_at'],
    MatterChecklist: ['matter_id', 'application_id', 'title', 'kind', 'done', 'version', 'completion_note', 'completed_at', 'completed_by_id', 'created_by_id', 'created_at'],
    MatterComment: ['matter_id', 'body', 'created_by_id', 'created_at'],
    FeePlan: ['title', 'matter_id', 'client_id', 'kind', 'amount', 'total_amount', 'periods', 'first_due_date', 'notes', 'created_by_id', 'created_at'],
    FeeInstallment: ['plan_id', 'entry_id', 'number', 'due_date', 'amount'],
    ClientAccess: ['membership_id', 'contact_id', 'created_by_id', 'created_at', 'revoked_at', 'revoked_by_id', 'revoke_reason'],
    DocumentReview: ['version_id', 'checksum', 'requested_by_id', 'reviewer_id', 'note', 'created_at'],
    ReviewDecision: ['review_id', 'actor_id', 'outcome', 'note', 'created_at'],
    Publication: ['review_id', 'access_id', 'title', 'note', 'published_by_id', 'created_at', 'revoked_at', 'revoked_by_id', 'revoke_reason'],
    PortalMessage: ['publication_id', 'actor_id', 'body', 'created_at'],
}


def extra_scope(user, organization, model, *, for_export=False):
    from apps.fees.services import visible_plans, visible_installments
    from apps.portal.services import visible_reviews, visible_publications, visible_accesses
    from apps.routines.services import visible_records, visible_templates
    if model is FeePlan:
        return visible_plans(user, organization, for_export=for_export)
    if model is FeeInstallment:
        return visible_installments(user, organization, for_export=for_export)
    if model is RoutineTemplate:
        templates = visible_templates(user, organization)
        if for_export:
            referenced = visible_records(user, organization, RoutineApplication).values('template_id')
            return RoutineTemplate.objects.filter(organization=organization).filter(Q(pk__in=templates.values('pk')) | Q(pk__in=referenced))
        return templates
    if model in {RoutineApplication, MatterChecklist, MatterComment}:
        return visible_records(user, organization, model)
    if model is DocumentReview:
        return visible_reviews(user, organization)
    if model is ReviewDecision:
        return ReviewDecision.objects.filter(organization=organization, review__in=visible_reviews(user, organization))
    if model is Publication:
        return visible_publications(user, organization, include_revoked=True)
    if model is PortalMessage:
        return PortalMessage.objects.filter(organization=organization, publication__in=visible_publications(user, organization, include_revoked=True))
    if model is ClientAccess:
        if for_export:
            referenced = visible_publications(user, organization, include_revoked=True).values('access_id')
            return ClientAccess.objects.filter(organization=organization).filter(Q(pk__in=visible_accesses(user, organization).values('pk')) | Q(pk__in=referenced))
        return visible_accesses(user, organization)
    return None
