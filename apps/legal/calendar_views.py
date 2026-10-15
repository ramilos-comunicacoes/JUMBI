from django.shortcuts import render
from django.views.decorators.http import require_GET

from .calendar_forms import CalendarFilterForm
from .calendar_services import calendar_context
from .views import organization_required


@organization_required
@require_GET
def calendar_view(request):
    from apps.core.preferences import office_preferences
    params = request.GET.copy()
    params.setdefault("view", office_preferences(request.organization)["calendar_view"])
    form = CalendarFilterForm(params, request=request)
    valid = form.is_valid()
    context = calendar_context(
        request,
        month=form.cleaned_data.get("month") if valid else None,
        selected_day=form.cleaned_data.get("day") if valid else None,
        kind=form.cleaned_data.get("kind", "") if valid else "",
        view=form.cleaned_data.get("view") if valid else "month",
        responsible=form.cleaned_data.get("responsible") if valid else None,
        status=form.cleaned_data.get("status", "all") if valid else "all",
        valid_filters=valid,
    )
    context.update({"page_title": "Calendário e agenda", "title": "Calendário e agenda", "active_nav": "appointments", "calendar_filter_form": form, "calendar_full": True})
    response = render(request, "legal/calendar.html", context, status=200 if valid else 400)
    response["Cache-Control"] = "private, no-store"
    return response
