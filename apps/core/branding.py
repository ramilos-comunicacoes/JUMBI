from .forms import OrganizationBrandingForm
from .models import AuditLog
from .services import has_permission, require_permission


def process_branding_form(request, organization):
    form = OrganizationBrandingForm(instance=organization, prefix="branding")
    saved = False
    if request.method == "POST" and request.POST.get("action") == "branding":
        require_permission(request.user, "core.change_branding", organization)
        form = OrganizationBrandingForm(
            request.POST,
            request.FILES,
            instance=organization,
            prefix="branding",
        )
        if form.is_valid():
            changed_fields = list(form.changed_data)
            form.save()
            AuditLog.objects.create(
                organization=organization,
                actor=request.user,
                action="core.organization.branding_changed",
                metadata={"changed_fields": changed_fields},
            )
            saved = True
    return {
        "branding_form": form,
        "can_manage_branding": has_permission(request.user, "core.change_branding", organization),
        "branding_saved": saved,
    }
