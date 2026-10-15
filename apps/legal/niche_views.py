"""Specialized hubs for specific legal practice areas (Previdenciário, Trabalhista, etc.).

Provides deep domain workflows instead of generic shells:
- Previdenciário: INSS demands, 30-day requirement deadlines, EC 103/2019 transition calculators, social security petitions.
- Trabalhista: Labor court claims, hearing preparation checklist (CLT art. 844), severance pay calculator (CLT/Lei 12.506).
"""

from datetime import date, timedelta
from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.niches import practice_area_values
from .models import AdministrativeDemand, Contact, CourtCase, Deadline, Matter, Task
from .services import visible_matters
from .views import can_edit, organization_required


@organization_required
@require_http_methods(["GET"])
def previdenciario_hub(request):
    """Deep Previdenciário Hub: INSS requirements, 30-day deadline alerts, EC 103 calculator & templates."""
    today = timezone.localdate()
    org = request.organization
    user = request.user
    user_matters = visible_matters(user, org)

    demands = AdministrativeDemand.objects.filter(
        organization=org,
        matter__in=user_matters,
    ).select_related("matter", "contact", "assigned_to").order_by("-updated_at")

    active_demands = demands.filter(
        status__in=[AdministrativeDemand.Status.PENDING, AdministrativeDemand.Status.REQUIREMENT, AdministrativeDemand.Status.SUSPENDED]
    )
    requirement_demands = demands.filter(status=AdministrativeDemand.Status.REQUIREMENT)
    concluded_demands = demands.filter(status=AdministrativeDemand.Status.CONCLUDED)
    rejected_demands = demands.filter(status=AdministrativeDemand.Status.REJECTED)

    # 30-day requirement urgency monitoring
    # INSS requirements typically have a strict 30-day fulfillment window (IN 128/2022)
    demands_with_deadlines = []
    for d in requirement_demands:
        fulfillment_deadline = d.requirement_due_date
        days_left = (fulfillment_deadline - today).days if fulfillment_deadline else None
        urgency = "unverified" if days_left is None else "overdue" if days_left < 0 else "urgent" if days_left <= 7 else "attention" if days_left <= 15 else "normal"
        demands_with_deadlines.append({
            "demand": d,
            "deadline_date": fulfillment_deadline,
            "days_left": days_left,
            "urgency": urgency,
        })

    # Related matters in previdenciário
    prev_area_values = practice_area_values("previdenciario")
    matters_prev = user_matters.filter(area__in=prev_area_values).select_related("client")[:10]

    return render(request, "legal/previdenciario_hub.html", {
        "page_title": "Direito Previdenciário & INSS",
        "active_nav": "demands",
        "today": today,
        "demands": demands[:15],
        "active_count": active_demands.count(),
        "requirement_count": requirement_demands.count(),
        "concluded_count": concluded_demands.count(),
        "rejected_count": rejected_demands.count(),
        "demands_with_deadlines": demands_with_deadlines[:10],
        "matters_prev": matters_prev,
        "can_edit": can_edit(request),
    })


@organization_required
@require_http_methods(["GET"])
def trabalhista_hub(request):
    """Deep Trabalhista Hub: Labor claims, hearing checklist (CLT 844), severance calculator & templates."""
    today = timezone.localdate()
    org = request.organization
    user = request.user
    user_matters = visible_matters(user, org)

    # Filter labor cases (TRT / TST / Vara do Trabalho)
    trab_area_values = practice_area_values("trabalhista")
    labor_matters = user_matters.filter(area__in=trab_area_values).select_related("client")

    labor_cases = CourtCase.objects.filter(
        organization=org,
        matter__in=user_matters,
    ).filter(
        Q(court__icontains="TRT") | Q(court__icontains="TST") | Q(court__icontains="Trabalho") |
        Q(matter__area__in=trab_area_values)
    ).select_related("matter").order_by("-created_at")

    # Upcoming labor deadlines and hearings
    upcoming_deadlines = Deadline.objects.filter(
        organization=org,
        matter__in=labor_matters,
        status=Deadline.Status.PENDING,
        due_date__gte=today,
    ).select_related("matter", "owner").order_by("due_date")[:8]

    # Related labor tasks
    labor_tasks = Task.objects.filter(
        organization=org,
        matter__in=labor_matters,
    ).exclude(status__in=[Task.Status.DONE, Task.Status.CANCELLED]).select_related("matter", "owner")[:8]

    return render(request, "legal/trabalhista_hub.html", {
        "page_title": "Direito Trabalhista & Audiências",
        "active_nav": "trabalhista",
        "today": today,
        "labor_matters": labor_matters[:10],
        "labor_cases": labor_cases[:15],
        "total_cases_count": labor_cases.count(),
        "upcoming_deadlines": upcoming_deadlines,
        "labor_tasks": labor_tasks,
        "can_edit": can_edit(request),
    })
