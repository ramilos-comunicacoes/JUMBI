from django.contrib import admin

from .models import (
    Partner,
    PartnerCampaign,
    PartnerCategory,
    PartnerMaterial,
    PartnerNetworkSettings,
    PartnerOpportunity,
    PartnerOpportunityEvent,
)


@admin.register(PartnerNetworkSettings)
class PartnerNetworkSettingsAdmin(admin.ModelAdmin):
    list_display = ("organization", "public_name", "is_enabled", "compliance_acknowledged", "updated_at")
    list_filter = ("is_enabled", "compliance_acknowledged")


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ("display_name", "organization", "category", "status", "email", "created_at")
    list_filter = ("status", "person_type", "category")
    search_fields = ("display_name", "email", "organization__name")


admin.site.register(PartnerCategory)
admin.site.register(PartnerCampaign)
admin.site.register(PartnerOpportunity)
admin.site.register(PartnerOpportunityEvent)
admin.site.register(PartnerMaterial)
