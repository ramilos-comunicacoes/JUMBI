from django import forms
from django.contrib import admin
from django.db import transaction
from apps.core.models import Organization
from .models import OrganizationSubscription, SubscriptionEvent
from .services import validate_plan_change


class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = OrganizationSubscription
        fields = "__all__"

    def clean(self):
        data = super().clean()
        if data.get("organization") and data.get("plan"):
            validate_plan_change(data["organization"], data["plan"], is_partner=data.get("is_partner", False))
        return data


@admin.register(OrganizationSubscription)
class SubscriptionAdmin(admin.ModelAdmin):
    form = SubscriptionForm
    list_display = ("organization", "plan", "is_partner", "status", "requested_plan", "expires_at")
    list_filter = ("is_partner", "plan", "status", "requested_plan")
    search_fields = ("organization__name", "organization__contact_email")
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(organization__business_type="office")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "organization":
            kwargs["queryset"] = Organization.objects.filter(business_type="office")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    has_change_permission = has_view_permission
    has_add_permission = has_view_permission

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return (*self.readonly_fields, "organization") if obj else self.readonly_fields

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=obj.organization_id)
            validate_plan_change(obj.organization, obj.plan, is_partner=obj.is_partner)
            super().save_model(request, obj, form, change)
            SubscriptionEvent.objects.create(subscription=obj, actor=request.user, description=f"Administração definiu plano={obj.plan}, parceiro gratuito e ilimitado={obj.is_partner}, situação={obj.status}, validade={obj.expires_at or 'manual'}. Alterações: {', '.join(form.changed_data)}. Não é comprovante de pagamento.")


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = ("subscription", "actor", "created_at", "description")
    def get_queryset(self, request):
        return super().get_queryset(request).filter(subscription__organization__business_type="office")
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
