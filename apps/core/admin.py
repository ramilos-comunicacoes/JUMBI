from django import forms
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import AuditLog, Membership, Organization, OrganizationRole, User


admin.site.site_header = "Jumbi Gestão Jurídica"
admin.site.site_title = "Administração Jumbi"
admin.site.index_title = "Controle da plataforma jurídica"
PLATFORM_ADMIN_APPS = {"auth", "core", "legal", "billing"}


def platform_groups():
    return Group.objects.exclude(permissions__in=Permission.objects.exclude(content_type__app_label__in=PLATFORM_ADMIN_APPS))


def office_users():
    # New active accounts may be awaiting their first membership. Isolation
    # disables inherited orphan accounts before the release accepts traffic.
    return User.objects.filter(
        Q(memberships__organization__business_type="office")
        | Q(is_superuser=True)
        | Q(is_active=True, memberships__isnull=True)
    ).distinct()


class OfficeRelationsMixin:
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        model = db_field.remote_field.model
        if model is Organization:
            kwargs["queryset"] = Organization.objects.filter(business_type="office")
        elif model is User:
            kwargs["queryset"] = office_users()
        elif model in {Membership, OrganizationRole}:
            kwargs["queryset"] = model.objects.filter(organization__business_type="office")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class OfficeRecordAdmin(OfficeRelationsMixin, admin.ModelAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(organization__business_type="office")


class PlatformUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User

    def clean(self):
        data = super().clean()
        if self.instance.pk and data.get("is_active") and User.objects.filter(pk=self.instance.pk, is_active=False).exists():
            from apps.billing.services import check_capacity
            organizations = Organization.objects.filter(
                memberships__user=self.instance, memberships__is_active=True, business_type="office",
            ).order_by("pk")
            # Django's admin wraps change forms in a transaction. Stable lock
            # order prevents competing reactivations from bypassing any quota.
            for organization in organizations:
                check_capacity(organization, "members", user=self.instance)
        return data


class PlatformMembershipForm(forms.ModelForm):
    class Meta:
        model = Membership
        fields = "__all__"

    def clean(self):
        data = super().clean()
        organization = data.get("organization") or getattr(self.instance, "organization", None)
        user = data.get("user") or getattr(self.instance, "user", None)
        previous = Membership.objects.filter(pk=self.instance.pk).values("organization_id", "user_id", "is_active").first() if self.instance.pk else None
        if previous and ((organization and organization.pk != previous["organization_id"]) or (user and user.pk != previous["user_id"])):
            raise ValidationError("Preserve o vínculo existente. Cadastre um novo acesso para outra pessoa ou escritório.")
        for field in ("position", "reports_to"):
            related = data.get(field)
            if related and organization and related.organization_id != organization.pk:
                self.add_error(field, "Selecione um registro do mesmo escritório.")
        if organization and user and user.is_active and data.get("is_active") and (not previous or not previous["is_active"]):
            from apps.billing.services import check_capacity
            check_capacity(organization, "members", user=user)
        return data


@admin.register(User)
class DjumbiUserAdmin(UserAdmin):
    model = User
    form = PlatformUserChangeForm
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")} ),
        ("Informacoes pessoais", {"fields": ("first_name", "last_name")} ),
        ("Permissoes", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")} ),
        ("Datas importantes", {"fields": ("last_login", "date_joined")} ),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(pk__in=office_users().values("pk"))

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "user_permissions":
            kwargs["queryset"] = Permission.objects.filter(content_type__app_label__in=PLATFORM_ADMIN_APPS)
        elif db_field.name == "groups":
            kwargs["queryset"] = platform_groups()
        return super().formfield_for_manytomany(db_field, request, **kwargs)


if admin.site.is_registered(Group):
    admin.site.unregister(Group)


@admin.register(Group)
class JumbiGroupAdmin(GroupAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(pk__in=platform_groups().values("pk"))

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "permissions":
            kwargs["queryset"] = Permission.objects.filter(content_type__app_label__in=PLATFORM_ADMIN_APPS)
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "business_type", "status", "city", "state", "created_at")
    list_filter = ("status", "state")
    search_fields = ("name", "legal_name", "document", "contact_email")

    def get_readonly_fields(self, request, obj=None):
        return () if request.user.is_superuser else ("practice_areas",)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "practice_areas":
            from django import forms
            from .niches import PRACTICE_AREAS
            return forms.MultipleChoiceField(label="Áreas de atuação", choices=PRACTICE_AREAS, required=False, widget=forms.CheckboxSelectMultiple)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(business_type="office")

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "business_type":
            kwargs["choices"] = [("office", "Jurídico")]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def get_changeform_initial_data(self, request):
        return {**super().get_changeform_initial_data(request), "business_type": "office"}


@admin.register(Membership)
class MembershipAdmin(OfficeRecordAdmin):
    form = PlatformMembershipForm
    list_display = ("user", "organization", "position", "role", "reports_to", "is_active", "created_at")
    list_filter = ("role", "is_active")
    search_fields = ("user__email", "organization__name")

    def get_readonly_fields(self, request, obj=None):
        return ("organization", "user") if obj else ()


@admin.register(OrganizationRole)
class OrganizationRoleAdmin(OfficeRecordAdmin):
    list_display = ("name", "organization", "hierarchy_level", "permission_role", "is_active")
    list_filter = ("permission_role", "is_active")
    search_fields = ("name", "organization__name")


@admin.register(AuditLog)
class AuditLogAdmin(OfficeRecordAdmin):
    list_display = ("action", "organization", "actor", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("organization__name", "actor__email", "action")
    readonly_fields = ("organization", "actor", "action", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
