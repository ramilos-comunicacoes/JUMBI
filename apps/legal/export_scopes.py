"""A matter ZIP contains only records tied to that matter, after live scoping."""
from django.db.models import Q


def matter_scope(queryset, matter):
    label = queryset.model._meta.label_lower
    relations = {
        "legal.matter": "pk", "legal.contact": None,
        "legal.courtcase": "matter_id", "legal.task": "matter_id",
        "legal.deadline": "matter_id", "legal.deadlinerevision": "deadline__matter_id",
        "legal.appointment": "matter_id", "legal.document": "matter_id",
        "legal.documentversion": "document__matter_id", "legal.financeentry": "matter_id",
        "legal.payment": "entry__matter_id", "contracts.contract": "matter_id",
        "contracts.contractrevision": "contract__matter_id",
        "contracts.contracttemplate": "contracts__matter_id",
        "routines.routinetemplate": "applications__matter_id",
        "routines.routineapplication": "matter_id", "routines.matterchecklist": "matter_id",
        "routines.mattercomment": "matter_id", "worklog.taskcomment": "task__matter_id",
        "fees.feeplan": "matter_id", "fees.feeinstallment": "plan__matter_id",
        "portal.documentreview": "version__document__matter_id",
        "portal.reviewdecision": "review__version__document__matter_id",
        "portal.publication": "review__version__document__matter_id",
        "portal.portalmessage": "publication__review__version__document__matter_id",
        "portal.clientaccess": "publications__review__version__document__matter_id",
    }
    if label == "legal.contact":
        return queryset.filter(pk=matter.client_id)
    if label not in relations:
        return queryset.none()
    return queryset.filter(**{relations[label]: matter.pk}).distinct()


def matter_audit(queryset, *, user, organization, matter, models):
    from .views import scoped_queryset
    allowed = Q(pk__in=[])
    for model in models:
        if model._meta.label_lower == "legal.auditevent":
            continue
        records = matter_scope(scoped_queryset(user, organization, model, for_export=True), matter)
        # Cast IDs to text because AuditEvent supports heterogeneous subjects.
        ids = [str(pk) for pk in records.values_list("pk", flat=True)]
        if ids:
            allowed |= Q(object_type=model._meta.label_lower, object_id__in=ids)
    return queryset.filter(allowed)
