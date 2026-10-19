from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.billing.services import has_advanced
from apps.portal.services import visible_accesses, visible_publications, visible_reviews
from .models import Contact, Document, DocumentVersion, Matter
from .services import visible_matters
from .views import accessible_audit, can_edit, organization_required, scoped_queryset


@organization_required
@require_GET
def contact_detail(request, pk):
    contact = get_object_or_404(scoped_queryset(request.user, request.organization, Contact), pk=pk)
    matters = visible_matters(request.user, request.organization).filter(client=contact).select_related("owner")
    grants = visible_accesses(request.user, request.organization).filter(contact=contact).select_related("membership__user")
    manager = request.membership.role in {"owner", "manager"}
    return render(request, "legal/contact_detail.html", {
        "page_title": contact.name, "active_nav": "contacts", "contact": contact,
        "can_edit": can_edit(request), "can_manage_portal": manager and has_advanced(request.organization),
        "show_portal_links": manager, "portal_grants": grants[:20], "portal_grant_count": grants.count(),
        "matters_page": Paginator(matters, 12).get_page(request.GET.get("page")),
        "matter_count": matters.count(), "active_matter_count": matters.exclude(status="closed").count(),
        "activity": accessible_audit(request.user, request.organization).filter(
            object_type=Contact._meta.label_lower, object_id=str(contact.pk)
        )[:12],
    })


@organization_required
@require_http_methods(["GET", "POST"])
def contact_delete(request, pk):
    if not can_edit(request):
        raise PermissionDenied("Seu perfil de acesso não possui permissão para excluir clientes.")
    contact = get_object_or_404(Contact.objects.filter(organization=request.organization), pk=pk)
    matters = Matter.objects.filter(organization=request.organization, client=contact)
    if request.method == "POST":
        from .services import delete_contact_and_matters
        matters_count = delete_contact_and_matters(contact=contact, actor=request.user)
        messages.success(request, f"Cliente {contact.name} e suas {matters_count} pasta(s) vinculada(s) foram excluídos com sucesso.")
        return redirect("legal:list", module="contacts")
    return render(request, "legal/contact_confirm_delete.html", {
        "page_title": f"Excluir {contact.name}",
        "active_nav": "contacts",
        "contact": contact,
        "matters": matters,
        "matters_count": matters.count(),
    })


@organization_required
@require_GET
def document_detail(request, pk):
    document = get_object_or_404(
        scoped_queryset(request.user, request.organization, Document).select_related("matter__client", "matter__owner", "created_by"), pk=pk
    )
    versions = scoped_queryset(request.user, request.organization, DocumentVersion).filter(document=document).select_related("uploaded_by")
    reviews = visible_reviews(request.user, request.organization).filter(version__document=document).select_related("version", "reviewer", "decision")
    publications = visible_publications(request.user, request.organization, include_revoked=True).filter(
        review__version__document=document
    ).select_related("review__version", "access__membership__user", "access")
    version_ids = [str(value) for value in versions.values_list("pk", flat=True)]
    events = accessible_audit(request.user, request.organization).filter(
        Q(object_type=Document._meta.label_lower, object_id=str(document.pk))
        | Q(object_type=DocumentVersion._meta.label_lower, object_id__in=version_ids)
    )
    return render(request, "legal/document_detail.html", {
        "page_title": document.title, "active_nav": "documents", "document": document,
        "latest_version": versions.first(), "versions_page": Paginator(versions, 10).get_page(request.GET.get("page")),
        "version_count": versions.count(), "can_edit": can_edit(request),
        "can_review": can_edit(request) and has_advanced(request.organization),
        "show_reviews": request.membership.role in {"owner", "manager", "operator"},
        "reviews": reviews[:20], "review_count": reviews.count(),
        "publications": publications[:20], "publication_count": publications.count(),
        "activity": events[:20],
    })
