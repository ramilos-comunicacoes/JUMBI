"""Export and audit scopes shared by the workspace's additional modules."""
from django.db.models import Q

from apps.fees.models import FeePlan, FeeInstallment
from apps.portal.models import ClientAccess, DocumentReview, ReviewDecision, Publication, PortalMessage
from apps.routines.models import RoutineTemplate, RoutineApplication, MatterChecklist, MatterComment
from apps.inventory.models import Category, Supplier, Product, StockLot, Movement, Purchase, PurchaseItem, Asset, AssetEvent
from apps.worklog.models import TaskComment


EXTRA_EXPORT_FIELDS = {
    TaskComment: ['task_id', 'body', 'created_by_id', 'created_at', 'operation_key'],
    Category: ['name'],
    Supplier: ['name', 'document', 'phone', 'email', 'is_active'],
    Product: ['code', 'name', 'category_id', 'unit', 'location', 'minimum_stock', 'is_active', 'created_at'],
    StockLot: ['product_id', 'code', 'expires_on', 'quantity', 'created_at'],
    Movement: ['product_id', 'lot_id', 'kind', 'quantity', 'balance_after', 'reason', 'actor_id', 'created_at', 'operation_key', 'reversal_of_id', 'purchase_item_id'],
    Purchase: ['supplier_id', 'reference', 'notes', 'purchased_on', 'status', 'created_by_id', 'created_at', 'received_at', 'received_by_id', 'cancellation_reason', 'operation_key'],
    PurchaseItem: ['purchase_id', 'product_id', 'quantity', 'unit_cost', 'lot_code', 'expires_on'],
    Asset: ['code', 'name', 'serial_number', 'category_id', 'location', 'custodian_id', 'acquired_on', 'acquisition_value', 'status', 'notes', 'created_at'],
    AssetEvent: ['asset_id', 'actor_id', 'reason', 'before', 'after', 'created_at'],
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
    if model is TaskComment:
        from apps.worklog.services import visible_comments
        return visible_comments(user, organization)
    if model._meta.app_label == 'inventory':
        from apps.inventory.services import visible_records as inventory_records
        return inventory_records(user, organization, model, for_export=for_export)
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
