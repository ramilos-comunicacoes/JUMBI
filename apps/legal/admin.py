"""Read-only tenant access; platform status grants no legal-content bypass."""
from django.contrib import admin

from .models import (
    Appointment, AuditEvent, Contact, CourtCase, Deadline, DeadlineRevision,
    Document, DocumentVersion, FinanceEntry, Matter, Opportunity, Payment, Task,
)


class PlatformReadOnlyAdmin(admin.ModelAdmin):
    list_display = ("__str__", "organization")
    list_filter = (("organization", admin.RelatedOnlyFieldListFilter),)
    list_select_related = ("organization",)
    actions = None

    def get_queryset(self, request):
        from .views import scoped_queryset, accessible_audit
        from apps.legal.services import can_manage_finance
        organization = getattr(request, "organization", None)
        if organization is None or not self.has_module_permission(request):
            return super().get_queryset(request).none()
        if self.model in {FinanceEntry, Payment} and not can_manage_finance(request.user, organization):
            return super().get_queryset(request).none()
        return accessible_audit(request.user, organization) if self.model is AuditEvent else scoped_queryset(request.user, organization, self.model)

    def has_module_permission(self, request):
        from apps.core.models import Membership
        return bool(request.user.is_active and request.user.is_superuser and Membership.objects.filter(user=request.user, organization=getattr(request, "organization", None), is_active=True, organization__status="active", role__in=["owner", "manager", "operator", "viewer"]).exists())

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request) and (obj is None or self.get_queryset(request).filter(pk=obj.pk).exists())

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DocumentVersion)
class DocumentVersionAdmin(PlatformReadOnlyAdmin):
    # Private storage deliberately has no public URL. Never render FileField's
    # default readonly widget (which would ask the storage for a URL).
    exclude = ("file",)
    readonly_fields = ("stored_filename",)
    list_display = ("document", "number", "organization", "uploaded_by", "created_at")

    @admin.display(description="Arquivo privado")
    def stored_filename(self, obj):
        return obj.original_name


for model in (
    Appointment, AuditEvent, Contact, CourtCase, Deadline, DeadlineRevision,
    Document, FinanceEntry, Matter, Opportunity, Payment, Task,
):
    admin.site.register(model, PlatformReadOnlyAdmin)
