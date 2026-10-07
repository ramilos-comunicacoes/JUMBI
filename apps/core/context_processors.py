from .services import active_organization, available_organizations


def organization_context(request):
    context = {"is_htmx": request.headers.get("HX-Request") == "true"}
    if not request.user.is_authenticated:
        return context
    context.update({
        "active_organization": active_organization(request),
        "available_organizations": available_organizations(request.user),
    })
    return context
