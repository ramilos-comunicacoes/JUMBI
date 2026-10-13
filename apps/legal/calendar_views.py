from django.shortcuts import render
from django.views.decorators.http import require_GET

from .calendar_forms import CalendarFilterForm
from .calendar_services import calendar_context
from .views import organization_required


@organization_required
@require_GET
def calendar_view(request):
    form = CalendarFilterForm(request.GET)
    valid = form.is_valid()
    context = calendar_context(
        request,
        month=form.cleaned_data.get("month") if valid else None,
        selected_day=form.cleaned_data.get("day") if valid else None,
        kind=form.cleaned_data.get("kind", "") if valid else "",
        view=form.cleaned_data.get("view") if valid else "month",
    )
    context.update({"page_title": "Calendário e agenda", "title": "Calendário e agenda", "active_nav": "appointments", "calendar_filter_form": form, "calendar_full": True})
    return render(request, "legal/calendar.html", context)
