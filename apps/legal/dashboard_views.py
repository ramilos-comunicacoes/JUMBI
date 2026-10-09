"""Operational overview: every number comes from records the viewer can access."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.shortcuts import render
from django.utils import timezone

from apps.billing.services import has_advanced
from apps.performance.services import dashboard_goals
from .calendar_services import calendar_context
from .calendar_forms import CalendarFilterForm
from .models import Appointment, Contact, CourtCase, Deadline, Document, FinanceEntry, Matter, Opportunity, Payment, Task
from .niches import filter_niche, niche_selection
from .views import accessible_audit, can_edit, can_manage_finance, scoped_queryset


def net_payments(queryset):
    totals = queryset.aggregate(
        received=Sum("amount", filter=Q(reversal_of__isnull=True)),
        reversed=Sum("amount", filter=Q(reversal_of__isnull=False)),
    )
    return (totals["received"] or Decimal("0")) - (totals["reversed"] or Decimal("0"))


def overview(request):
    today = timezone.localdate()
    niche, choices = niche_selection(request)
    matters = filter_niche(scoped_queryset(request.user, request.organization, Matter), niche, choices)

    def scoped(model):
        queryset = scoped_queryset(request.user, request.organization, model)
        return filter_niche(queryset, niche, choices, relation="matter__")

    tasks = scoped(Task)
    pending = tasks.exclude(status=Task.Status.DONE)
    deadlines = scoped(Deadline).exclude(status=Deadline.Status.FULFILLED)
    appointments = scoped(Appointment).filter(ends_at__gte=timezone.now()).order_by("starts_at")
    finance_allowed = can_manage_finance(request)
    receivable = received = expenses = None
    if finance_allowed:
        entries = scoped(FinanceEntry)
        income = entries.filter(kind=FinanceEntry.Kind.INCOME)
        payments = Payment.objects.filter(organization=request.organization, entry__in=entries)
        income_total = income.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        paid = net_payments(payments.filter(entry__in=income))
        receivable = income_total - paid
        month_payments = payments.filter(date__gte=today.replace(day=1), date__lte=today)
        received = net_payments(month_payments.filter(entry__kind=FinanceEntry.Kind.INCOME))
        expenses = net_payments(month_payments.filter(entry__kind=FinanceEntry.Kind.EXPENSE))
    distribution = []
    active = matters.exclude(status=Matter.Status.CLOSED)
    active_total = active.count()
    for code, label in choices:
        count = filter_niche(active, code, choices).count()
        distribution.append({"code": code, "label": label, "count": count, "percent": round(count / active_total * 100) if active_total else 0})
    months = []
    first = today.replace(day=1)
    for offset in range(5, -1, -1):
        index = first.year * 12 + first.month - 1 - offset
        start = first.replace(year=index // 12, month=index % 12 + 1)
        stop = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        months.append({"label": start.strftime("%m/%y"), "count": matters.filter(created_at__date__gte=start, created_at__date__lt=stop).count()})
    peak = max((item["count"] for item in months), default=1) or 1
    for item in months:
        item["height"] = max(3, round(item["count"] / peak * 100))
    crm = []
    if has_advanced(request.organization):
        opportunities = scoped_queryset(request.user, request.organization, Opportunity)
        if niche:
            opportunities = opportunities.filter(contact_id__in=matters.values("client_id"))
        crm = [{"label": label, "count": opportunities.filter(stage=code).count()} for code, label in Opportunity.Stage.choices]
    calendar_form = CalendarFilterForm(request.GET)
    valid_calendar = calendar_form.is_valid()
    context = calendar_context(request,
        month=calendar_form.cleaned_data.get("month") if valid_calendar else None,
        selected_day=calendar_form.cleaned_data.get("day") if valid_calendar else None,
        kind=calendar_form.cleaned_data.get("kind", "") if valid_calendar else "")
    context.update({
        "title": "Dashboard", "page_title": "Dashboard", "active_nav": "dashboard", "today": today,
        "niche": niche, "niche_choices": choices, "niche_distribution": distribution,
        "stats": {"matters": active_total, "tasks": pending.count(), "deadlines": deadlines.count(), "receivable": receivable},
        "overdue_tasks": pending.filter(due_date__lt=today).count(),
        "overdue_deadlines": deadlines.filter(due_date__lt=today).count(),
        "unconfirmed_deadlines": deadlines.filter(status=Deadline.Status.PENDING).count(),
        "due_today": deadlines.filter(due_date=today).count(),
        "completed_tasks": tasks.filter(status=Task.Status.DONE).count(),
        "case_count": scoped(CourtCase).count(), "document_count": scoped(Document).count(),
        "contact_count": Contact.objects.filter(organization=request.organization, pk__in=matters.exclude(client=None).values("client_id")).count(),
        "upcoming_deadlines": deadlines.select_related("matter", "owner").order_by("due_date")[:6],
        "pending_tasks": pending.select_related("matter", "owner").order_by("due_date")[:5],
        "recent_matters": matters.select_related("client", "owner").order_by("-created_at")[:5],
        "next_appointments": appointments.select_related("matter", "owner")[:4],
        "activity": accessible_audit(request.user, request.organization, request.membership.role)[:5],
        "goal_cards": dashboard_goals(request.user, request.organization, niche=niche),
        "monthly_received": received, "monthly_expenses": expenses,
        "matter_trend": months, "crm_summary": crm, "can_edit": can_edit(request),
        "can_manage_finance": finance_allowed, "can_use_contracts": has_advanced(request.organization),
    })
    return render(request, "legal/dashboard.html", context)
