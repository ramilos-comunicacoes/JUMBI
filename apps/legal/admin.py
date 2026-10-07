"""Read-only support access; domain mutations stay in validated app services."""
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
        return super().get_queryset(request).filter(organization__business_type="office")

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

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
