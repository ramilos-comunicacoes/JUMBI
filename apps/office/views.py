from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.branding import process_branding_form
from apps.core.models import AuditLog
from apps.core.navigation import SEGMENT_APPS, app_shell_context
from apps.core.services import has_permission, require_business_organization, require_permission, transition
from apps.core.team import team_management_context
from apps.partners.views import partner_workspace_context

from .forms import LegalCaseForm, LegalDocumentForm, OfficeFinanceEntryForm, OfficePurchaseForm, StaffMemberForm, ClientForm, WorkItemForm
from .models import (
    Client,
    LegalCase,
    LegalDocument,
    MatterType,
    OfficeFinanceEntry,
    OfficePurchase,
    PracticeArea,
    StaffMember,
    WorkItem,
)


TASK_TRANSITIONS = {
    WorkItem.Status.TODO: {WorkItem.Status.IN_PROGRESS, WorkItem.Status.DONE},
    WorkItem.Status.IN_PROGRESS: {WorkItem.Status.TODO, WorkItem.Status.DONE},
    WorkItem.Status.DONE: {WorkItem.Status.IN_PROGRESS},
}

CASE_TRANSITIONS = {
    LegalCase.Status.INTAKE: {LegalCase.Status.ACTIVE, LegalCase.Status.WAITING, LegalCase.Status.CLOSED},
    LegalCase.Status.ACTIVE: {LegalCase.Status.WAITING, LegalCase.Status.CLOSED},
    LegalCase.Status.WAITING: {LegalCase.Status.ACTIVE, LegalCase.Status.CLOSED},
    LegalCase.Status.CLOSED: {LegalCase.Status.ACTIVE},
}


def _boolean_from_post(value):
    if value in {"1", "true", "True", "on"}:
        return True
    if value in {"0", "false", "False", "off"}:
        return False
    raise ValueError


def _visible_cases(user, organization):
    queryset = LegalCase.objects.filter(organization=organization)
    if has_permission(user, "office.view_confidential_case", organization):
        return queryset
    return queryset.filter(confidential=False)


@login_required
def workspace(request, section="overview"):
    shell_context = app_shell_context("office", section)
    if shell_context is None:
        raise Http404("Módulo jurídico não encontrado.")
    organization = require_business_organization(
        request, SEGMENT_APPS["office"]["business_type"]
    )
    can_view_confidential = has_permission(
        request.user, "office.view_confidential_case", organization
    )
    visible_cases = _visible_cases(request.user, organization)

    def redirect_to_section():
        if section == "overview":
            return redirect("office:workspace")
        return redirect("office:section", section=section)

    branding_context = process_branding_form(request, organization)
    if branding_context["branding_saved"]:
        messages.success(request, "Identidade visual da organização atualizada.")
        return redirect_to_section()

    if section == "partners":
        require_permission(request.user, "partners.view_network", organization)
        partner_context = partner_workspace_context(request, organization)
        if partner_context["partner_workspace_saved_message"]:
            messages.success(request, partner_context["partner_workspace_saved_message"])
            return redirect_to_section()
        return render(
            request,
            "office/workspace.html",
            {
                **shell_context,
                **branding_context,
                **partner_context,
                "organization": organization,
            },
        )

    team_context = {}
    if section == "accesses":
        require_permission(request.user, "core.manage_members", organization)
        team_context = team_management_context(request, organization)
        if team_context["team_saved"]:
            messages.success(request, team_context["team_success_message"])
            return redirect_to_section()

    client_form = ClientForm(prefix="client")
    task_form = WorkItemForm(
        prefix="task", organization=organization, case_queryset=visible_cases
    )
    staff_form = StaffMemberForm(prefix="staff")
    case_form = LegalCaseForm(
        prefix="case",
        organization=organization,
        can_mark_confidential=has_permission(
            request.user, "office.mark_confidential_case", organization
        ),
    )
    document_form = LegalDocumentForm(
        prefix="document", organization=organization, case_queryset=visible_cases
    )
    finance_form = OfficeFinanceEntryForm(
        prefix="finance", organization=organization, case_queryset=visible_cases
    )
    purchase_form = OfficePurchaseForm(prefix="purchase")
    if request.method == "POST":
        if request.POST.get("action") == "client":
            require_permission(request.user, "office.add_client", organization)
            client_form = ClientForm(request.POST, prefix="client")
            if client_form.is_valid():
                client = client_form.save(commit=False)
                client.organization = organization
                client.save()
                messages.success(request, "Cliente cadastrado no Jumbi.")
                return redirect_to_section()
        elif request.POST.get("action") == "task":
            require_permission(request.user, "office.add_task", organization)
            task_form = WorkItemForm(
                request.POST,
                prefix="task",
                organization=organization,
                case_queryset=visible_cases,
            )
            if task_form.is_valid():
                task = task_form.save(commit=False)
                task.organization = organization
                task.owner = request.user
                task.save()
                messages.success(request, "Tarefa criada no Jumbi.")
                return redirect_to_section()
        elif request.POST.get("action") == "staff":
            require_permission(request.user, "office.add_staff", organization)
            staff_form = StaffMemberForm(request.POST, prefix="staff")
            if staff_form.is_valid():
                staff = staff_form.save(commit=False)
                staff.organization = organization
                staff.save()
                messages.success(request, "Membro da equipe cadastrado.")
                return redirect_to_section()
        elif request.POST.get("action") == "case":
            require_permission(request.user, "office.add_case", organization)
            case_form = LegalCaseForm(
                request.POST,
                prefix="case",
                organization=organization,
                can_mark_confidential=has_permission(
                    request.user, "office.mark_confidential_case", organization
                ),
            )
            if case_form.is_valid():
                with transaction.atomic():
                    case = case_form.save(commit=False)
                    case.organization = organization
                    case.save()
                    checklist_steps = (
                        case.matter_type.workflow_steps
                        if case.matter_type and case_form.cleaned_data["create_initial_checklist"]
                        else []
                    )
                    checklist_items = [
                        WorkItem(
                            organization=organization,
                            client=case.client,
                            case=case,
                            title=step,
                            kind=WorkItem.Kind.TASK,
                            priority=WorkItem.Priority.NORMAL,
                            owner=request.user,
                        )
                        for step in checklist_steps
                        if isinstance(step, str) and step.strip()
                    ]
                    WorkItem.objects.bulk_create(checklist_items)
                    AuditLog.objects.create(
                        organization=organization,
                        actor=request.user,
                        action="office.legalcase.created",
                        metadata={
                            "id": str(case.pk),
                            "practice_area": case.practice_area.name if case.practice_area else "",
                            "matter_type": case.matter_type.name if case.matter_type else "",
                            "checklist_items": len(checklist_items),
                        },
                    )
                checklist_message = (
                    f" e {len(checklist_items)} etapas adicionadas à agenda"
                    if checklist_items
                    else ""
                )
                messages.success(request, f"Caso/processo cadastrado{checklist_message}.")
                return redirect_to_section()
        elif request.POST.get("action") == "document":
            require_permission(request.user, "office.add_document", organization)
            document_form = LegalDocumentForm(
                request.POST,
                request.FILES,
                prefix="document",
                organization=organization,
                case_queryset=visible_cases,
            )
            if document_form.is_valid():
                document = document_form.save(commit=False)
                document.organization = organization
                document.save()
                messages.success(request, "Documento juridico registrado.")
                return redirect_to_section()
        elif request.POST.get("action") == "finance":
            require_permission(request.user, "office.add_finance", organization)
            finance_form = OfficeFinanceEntryForm(
                request.POST,
                prefix="finance",
                organization=organization,
                case_queryset=visible_cases,
            )
            if finance_form.is_valid():
                entry = finance_form.save(commit=False)
                entry.organization = organization
                entry.save()
                messages.success(request, "Lancamento financeiro registrado.")
                return redirect_to_section()
        elif request.POST.get("action") == "purchase":
            require_permission(request.user, "office.add_purchase", organization)
            purchase_form = OfficePurchaseForm(request.POST, prefix="purchase")
            if purchase_form.is_valid():
                purchase = purchase_form.save(commit=False)
                purchase.organization = organization
                purchase.save()
                messages.success(request, "Compra administrativa registrada.")
                return redirect_to_section()
    today = timezone.localdate()
    case_visibility = Q(case__isnull=True)
    if can_view_confidential:
        case_visibility |= Q(case__organization=organization)
    else:
        case_visibility |= Q(case__organization=organization, case__confidential=False)
    tasks = WorkItem.objects.filter(
        Q(organization=organization) & case_visibility
    ).select_related("client", "case")
    finance_entries = OfficeFinanceEntry.objects.filter(
        Q(organization=organization) & case_visibility
    ).select_related("client", "case")
    cases = visible_cases.select_related(
        "client", "responsible", "practice_area", "matter_type"
    )
    active_matter_types = MatterType.objects.filter(is_active=True).select_related("practice_area")
    practice_case_filter = Q(cases__organization=organization) & ~Q(
        cases__status=LegalCase.Status.CLOSED
    )
    if not can_view_confidential:
        practice_case_filter &= Q(cases__confidential=False)
    practice_areas = (
        PracticeArea.objects.filter(is_active=True)
        .annotate(
            active_case_count=Count(
                "cases",
                filter=practice_case_filter,
                distinct=True,
            ),
            template_count=Count("matter_types", filter=Q(matter_types__is_active=True), distinct=True),
        )
        .prefetch_related(
            Prefetch(
                "matter_types",
                queryset=active_matter_types,
                to_attr="active_matter_types",
            )
        )
    )
    revenue_total = sum(
        (entry.amount for entry in finance_entries if entry.kind == OfficeFinanceEntry.Kind.REVENUE),
        start=0,
    )
    expense_total = sum(
        (entry.amount for entry in finance_entries if entry.kind == OfficeFinanceEntry.Kind.EXPENSE),
        start=0,
    )
    overdue_tasks = tasks.exclude(status=WorkItem.Status.DONE).filter(due_date__lt=today)
    todo_tasks = tasks.filter(status=WorkItem.Status.TODO).exclude(pk__in=overdue_tasks.values("pk"))
    progress_tasks = tasks.filter(status=WorkItem.Status.IN_PROGRESS).exclude(pk__in=overdue_tasks.values("pk"))
    done_tasks = tasks.filter(status=WorkItem.Status.DONE)
    client_case_filter = Q(cases__organization=organization)
    if not can_view_confidential:
        client_case_filter &= Q(cases__confidential=False)
    clients = Client.objects.filter(organization=organization).annotate(
        visible_case_count=Count("cases", filter=client_case_filter, distinct=True)
    )
    documents = LegalDocument.objects.filter(
        Q(organization=organization) & case_visibility
    ).select_related("case", "client")
    context = {
        **shell_context,
        **branding_context,
        **team_context,
        "organization": organization,
        "client_form": client_form,
        "task_form": task_form,
        "staff_form": staff_form,
        "case_form": case_form,
        "document_form": document_form,
        "finance_form": finance_form,
        "purchase_form": purchase_form,
        "clients": clients,
        "tasks": tasks,
        "overdue_tasks": overdue_tasks,
        "todo_tasks": todo_tasks,
        "progress_tasks": progress_tasks,
        "done_tasks": done_tasks,
        "staff_members": StaffMember.objects.filter(organization=organization),
        "cases": cases,
        "practice_areas": practice_areas,
        "matter_types": active_matter_types,
        "practice_area_count": practice_areas.count(),
        "matter_type_count": active_matter_types.count(),
        "classified_case_count": cases.exclude(practice_area=None).count(),
        "documents": documents,
        "finance_entries": finance_entries,
        "purchases": OfficePurchase.objects.filter(organization=organization),
        "today": today,
        "case_intake_count": cases.filter(status=LegalCase.Status.INTAKE).count(),
        "case_active_count": cases.filter(status=LegalCase.Status.ACTIVE).count(),
        "case_waiting_count": cases.filter(status=LegalCase.Status.WAITING).count(),
        "case_closed_count": cases.filter(status=LegalCase.Status.CLOSED).count(),
        "open_cases": cases.exclude(status=LegalCase.Status.CLOSED).count(),
        "open_tasks": tasks.exclude(status=WorkItem.Status.DONE).count(),
        "overdue_tasks_count": overdue_tasks.count(),
        "revenue_total": revenue_total,
        "expense_total": expense_total,
        "finance_balance": revenue_total - expense_total,
        "finance_pending_count": finance_entries.filter(paid=False).count(),
        "purchases_pending_count": OfficePurchase.objects.filter(organization=organization, paid=False).count(),
    }
    return render(request, "office/workspace.html", context)


@login_required
@require_POST
def task_status(request, pk):
    organization = require_business_organization(
        request, SEGMENT_APPS["office"]["business_type"]
    )
    tasks = WorkItem.objects.filter(organization=organization)
    if not has_permission(request.user, "office.view_confidential_case", organization):
        tasks = tasks.filter(Q(case__isnull=True) | Q(case__confidential=False))
    task = tasks.filter(pk=pk).first()
    if task is None:
        return HttpResponseBadRequest("Tarefa não encontrada para a organização ativa.")
    try:
        transition(
            instance=task,
            target_status=request.POST["status"],
            actor=request.user,
            permission="office.change_task_status",
            transition_map=TASK_TRANSITIONS,
        )
    except KeyError:
        return HttpResponseBadRequest("Status obrigatório.")
    except ValidationError as exc:
        return HttpResponseBadRequest(exc.messages[0])
    return redirect("office:section", section="tasks")


@login_required
@require_POST
def case_status(request, pk):
    organization = require_business_organization(
        request, SEGMENT_APPS["office"]["business_type"]
    )
    case = _visible_cases(request.user, organization).filter(pk=pk).first()
    if case is None:
        return HttpResponseBadRequest("Processo não encontrado para a organização ativa.")
    try:
        transition(
            instance=case,
            target_status=request.POST["status"],
            actor=request.user,
            permission="office.change_case_status",
            transition_map=CASE_TRANSITIONS,
        )
    except KeyError:
        return HttpResponseBadRequest("Status obrigatório.")
    except ValidationError as exc:
        return HttpResponseBadRequest(exc.messages[0])
    return redirect("office:section", section="cases")


@login_required
@require_POST
def finance_paid(request, pk):
    organization = require_business_organization(
        request, SEGMENT_APPS["office"]["business_type"]
    )
    entries = OfficeFinanceEntry.objects.filter(organization=organization)
    if not has_permission(request.user, "office.view_confidential_case", organization):
        entries = entries.filter(Q(case__isnull=True) | Q(case__confidential=False))
    entry = entries.filter(pk=pk).first()
    if entry is None:
        return HttpResponseBadRequest("Lançamento não encontrado para a organização ativa.")
    require_permission(request.user, "office.change_finance_status", organization)
    try:
        paid = _boolean_from_post(request.POST["paid"])
    except (KeyError, ValueError):
        return HttpResponseBadRequest("Situação financeira inválida.")
    before = entry.paid
    entry.paid = paid
    entry.save(update_fields=["paid"])
    AuditLog.objects.create(
        organization=organization,
        actor=request.user,
        action="office.officefinanceentry.payment_changed",
        metadata={"before": before, "after": paid, "id": str(entry.pk)},
    )
    return redirect("office:section", section="finance")


@login_required
@require_POST
def purchase_paid(request, pk):
    organization = require_business_organization(
        request, SEGMENT_APPS["office"]["business_type"]
    )
    purchase = OfficePurchase.objects.filter(organization=organization, pk=pk).first()
    if purchase is None:
        return HttpResponseBadRequest("Compra não encontrada para a organização ativa.")
    require_permission(request.user, "office.change_purchase_status", organization)
    try:
        paid = _boolean_from_post(request.POST["paid"])
    except (KeyError, ValueError):
        return HttpResponseBadRequest("Situação da compra inválida.")
    before = purchase.paid
    purchase.paid = paid
    purchase.save(update_fields=["paid"])
    AuditLog.objects.create(
        organization=organization,
        actor=request.user,
        action="office.officepurchase.payment_changed",
        metadata={"before": before, "after": paid, "id": str(purchase.pk)},
    )
    return redirect("office:section", section="purchases")
