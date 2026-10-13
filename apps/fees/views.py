from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.billing.services import require_access
from apps.legal.services import can_manage_finance
from apps.legal.views import organization_required
from .forms import FeePlanForm
from .services import create_plan, installment_rows, visible_plans


def fees_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require_access(request.organization, advanced=True)
        if not can_manage_finance(request.user, request.organization):
            raise PermissionDenied("Honorários estão disponíveis aos perfis de direção e gestão.")
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response
    return organization_required(wrapped)


def context(**extra):
    return {"page_title": "Honorários", "active_nav": "fees", **extra}


@require_GET
@fees_access
def overview(request):
    plans = visible_plans(request.user, request.organization).select_related("client", "matter")
    query = request.GET.get("q", "").strip()[:200]
    if query:
        plans = plans.filter(Q(title__icontains=query) | Q(client__name__icontains=query) | Q(matter__title__icontains=query))
    page = Paginator(plans, 24).get_page(request.GET.get("page"))
    return render(request, "fees/overview.html", context(plans=page, query=query))


@require_http_methods(["GET", "POST"])
@fees_access
def create(request):
    form = FeePlanForm(request.POST if request.method == "POST" else None, actor=request.user, organization=request.organization)
    preview, total = [], None
    if request.method == "POST" and form.is_valid():
        preview = form.schedule
        total = sum(row["amount"] for row in preview)
        if request.POST.get("action") == "create":
            if not form.cleaned_data["reviewed"]:
                form.add_error("reviewed", "Confira o cronograma e marque a confirmação antes de registrar.")
            else:
                data = {key: value for key, value in form.cleaned_data.items() if key != "reviewed"}
                try:
                    plan = create_plan(organization=request.organization, actor=request.user, **data)
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, "Acordo registrado. As parcelas já estão no financeiro, sem registrar recebimento.")
                    return redirect("fees:detail", pk=plan.pk)
    return render(request, "fees/form.html", context(form=form, preview=preview, total=total))


@require_GET
@fees_access
def detail(request, pk):
    plan = get_object_or_404(visible_plans(request.user, request.organization).select_related("client", "matter", "created_by"), pk=pk)
    rows = installment_rows(plan)
    paid = sum((row.net_paid for row in rows), Decimal("0.00"))
    return render(request, "fees/detail.html", context(plan=plan, rows=rows, paid=paid, balance=plan.total_amount - paid))
