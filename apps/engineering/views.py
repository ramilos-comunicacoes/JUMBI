from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.core.branding import process_branding_form
from apps.core.navigation import SEGMENT_APPS, app_shell_context
from apps.core.services import active_membership, require_business_organization, require_permission, transition
from apps.core.team import team_management_context

from .forms import EmployeeForm, FinanceEntryForm, ProjectEvidenceForm, ProjectForm, ProjectTaskForm, PurchaseForm, SupplierForm
from .models import Employee, FinanceEntry, Project, ProjectEvidence, ProjectTask, Purchase, Supplier


PROJECT_TRANSITIONS = {
    Project.Status.PLANNING: {Project.Status.ACTIVE},
    Project.Status.ACTIVE: {Project.Status.PLANNING, Project.Status.COMPLETED},
    Project.Status.COMPLETED: {Project.Status.ACTIVE},
}

TASK_TRANSITIONS = {
    ProjectTask.Status.TODO: {ProjectTask.Status.DOING},
    ProjectTask.Status.DOING: {ProjectTask.Status.TODO, ProjectTask.Status.REVIEW, ProjectTask.Status.DONE},
    ProjectTask.Status.REVIEW: {ProjectTask.Status.DOING, ProjectTask.Status.DONE},
    ProjectTask.Status.DONE: {ProjectTask.Status.DOING},
}


@login_required
def workspace(request, section="overview"):
    if settings.JUMBI_LEGAL_ONLY:
        return redirect("office:workspace")
    shell_context = app_shell_context("engineering", section)
    if shell_context is None:
        raise Http404("Módulo de engenharia não encontrado.")
    organization = require_business_organization(
        request, SEGMENT_APPS["engineering"]["business_type"]
    )

    def redirect_to_section():
        if section == "overview":
            return redirect("engineering:workspace")
        return redirect("engineering:section", section=section)

    branding_context = process_branding_form(request, organization)
    if branding_context["branding_saved"]:
        messages.success(request, "Identidade visual da organização atualizada.")
        return redirect_to_section()

    team_context = {}
    if section == "accesses":
        require_permission(request.user, "core.manage_members", organization)
        team_context = team_management_context(request, organization)
        if team_context["team_saved"]:
            messages.success(request, team_context["team_success_message"])
            return redirect_to_section()

    project_form = ProjectForm(prefix="project")
    supplier_form = SupplierForm(prefix="supplier")
    task_form = ProjectTaskForm(prefix="task", organization=organization)
    evidence_form = ProjectEvidenceForm(prefix="evidence", organization=organization)
    employee_form = EmployeeForm(prefix="employee", organization=organization)
    finance_form = FinanceEntryForm(prefix="finance", organization=organization)
    purchase_form = PurchaseForm(prefix="purchase", organization=organization)
    if request.method == "POST":
        if request.POST.get("action") == "project":
            require_permission(request.user, "engineering.add_project", organization)
            project_form = ProjectForm(request.POST, prefix="project")
            if project_form.is_valid():
                project = project_form.save(commit=False)
                project.organization = organization
                project.save()
                messages.success(request, "Obra cadastrada na Engenharia.")
                return redirect_to_section()
        elif request.POST.get("action") == "supplier":
            require_permission(request.user, "engineering.add_supplier", organization)
            supplier_form = SupplierForm(request.POST, prefix="supplier")
            if supplier_form.is_valid():
                supplier = supplier_form.save(commit=False)
                supplier.organization = organization
                supplier.save()
                messages.success(request, "Fornecedor cadastrado na Engenharia.")
                return redirect_to_section()
        elif request.POST.get("action") == "task":
            require_permission(request.user, "engineering.add_task", organization)
            task_form = ProjectTaskForm(request.POST, prefix="task", organization=organization)
            if task_form.is_valid():
                task = task_form.save(commit=False)
                task.organization = organization
                task.created_by = request.user
                task.save()
                messages.success(request, "Tarefa criada no painel de obra.")
                return redirect_to_section()
        elif request.POST.get("action") == "evidence":
            require_permission(request.user, "engineering.add_evidence", organization)
            evidence_form = ProjectEvidenceForm(request.POST, request.FILES, prefix="evidence", organization=organization)
            if evidence_form.is_valid():
                evidence = evidence_form.save(commit=False)
                evidence.organization = organization
                evidence.created_by = request.user
                evidence.save()
                messages.success(request, "Evidencia registrada na obra.")
                return redirect_to_section()
        elif request.POST.get("action") == "employee":
            require_permission(request.user, "engineering.add_employee", organization)
            employee_form = EmployeeForm(request.POST, prefix="employee", organization=organization)
            if employee_form.is_valid():
                employee = employee_form.save(commit=False)
                employee.organization = organization
                employee.save()
                messages.success(request, "Funcionario cadastrado na Engenharia.")
                return redirect_to_section()
        elif request.POST.get("action") == "finance":
            require_permission(request.user, "engineering.add_finance", organization)
            finance_form = FinanceEntryForm(request.POST, prefix="finance", organization=organization)
            if finance_form.is_valid():
                entry = finance_form.save(commit=False)
                entry.organization = organization
                entry.save()
                messages.success(request, "Lancamento financeiro registrado.")
                return redirect_to_section()
        elif request.POST.get("action") == "purchase":
            require_permission(request.user, "engineering.add_purchase", organization)
            purchase_form = PurchaseForm(request.POST, prefix="purchase", organization=organization)
            if purchase_form.is_valid():
                purchase = purchase_form.save(commit=False)
                purchase.organization = organization
                purchase.save()
                messages.success(request, "Compra registrada na Engenharia.")
                return redirect_to_section()
    projects = Project.objects.filter(organization=organization).prefetch_related("tasks", "evidences")
    tasks = ProjectTask.objects.filter(organization=organization).select_related("project", "assignee")
    evidences = ProjectEvidence.objects.filter(organization=organization).select_related("project", "task", "created_by")[:8]
    finance_entries = FinanceEntry.objects.filter(organization=organization).select_related("project")[:8]
    purchases = Purchase.objects.filter(organization=organization).select_related("project", "supplier")[:8]
    employees = Employee.objects.filter(organization=organization).select_related("project")
    kanban = {
        "todo": tasks.filter(status=ProjectTask.Status.TODO),
        "doing": tasks.filter(status=ProjectTask.Status.DOING),
        "review": tasks.filter(status=ProjectTask.Status.REVIEW),
        "done": tasks.filter(status=ProjectTask.Status.DONE),
    }
    total_budget = sum((project.budget for project in projects), start=0)
    context = {
        **shell_context,
        **branding_context,
        **team_context,
        "organization": organization,
        "project_form": project_form,
        "supplier_form": supplier_form,
        "task_form": task_form,
        "evidence_form": evidence_form,
        "employee_form": employee_form,
        "finance_form": finance_form,
        "purchase_form": purchase_form,
        "projects": projects,
        "tasks": tasks,
        "kanban": kanban,
        "evidences": evidences,
        "finance_entries": finance_entries,
        "purchases": purchases,
        "employees": employees,
        "suppliers": Supplier.objects.filter(organization=organization),
        "total_budget": total_budget,
        "active_projects": projects.filter(status=Project.Status.ACTIVE).count(),
        "open_tasks": tasks.exclude(status=ProjectTask.Status.DONE).count(),
        "review_tasks": tasks.filter(status=ProjectTask.Status.REVIEW).count(),
        "finance_balance": sum((entry.amount if entry.kind == FinanceEntry.Kind.REVENUE else -entry.amount for entry in FinanceEntry.objects.filter(organization=organization)), start=0),
    }
    return render(request, "engineering/workspace.html", context)


@login_required
@require_http_methods(["POST"])
def project_status(request, pk):
    if settings.JUMBI_LEGAL_ONLY:
        return redirect("office:workspace")
    organization = require_business_organization(
        request, SEGMENT_APPS["engineering"]["business_type"]
    )
    membership = active_membership(request)
    projects = Project.objects.filter(organization=organization) if request.user.is_superuser else Project.objects.for_membership(membership)
    project = projects.filter(pk=pk).first()
    if project is None:
        return HttpResponseBadRequest("Obra nao encontrada para a organizacao ativa.")
    try:
        transition(
            instance=project,
            target_status=request.POST["status"],
            actor=request.user,
            permission="engineering.change_project_status",
            transition_map=PROJECT_TRANSITIONS,
        )
    except KeyError:
        return HttpResponseBadRequest("Status obrigatorio.")
    except ValidationError as exc:
        return HttpResponseBadRequest(exc.messages[0])
    return render(request, "engineering/partials/project_row.html", {"project": project})


@login_required
@require_http_methods(["POST"])
def task_status(request, pk):
    if settings.JUMBI_LEGAL_ONLY:
        return redirect("office:workspace")
    organization = require_business_organization(
        request, SEGMENT_APPS["engineering"]["business_type"]
    )
    membership = active_membership(request)
    tasks = ProjectTask.objects.filter(organization=organization) if request.user.is_superuser else ProjectTask.objects.for_membership(membership)
    task = tasks.select_related("project", "assignee").filter(pk=pk).first()
    if task is None:
        return HttpResponseBadRequest("Tarefa nao encontrada para a organizacao ativa.")
    try:
        transition(
            instance=task,
            target_status=request.POST["status"],
            actor=request.user,
            permission="engineering.change_task_status",
            transition_map=TASK_TRANSITIONS,
        )
    except KeyError:
        return HttpResponseBadRequest("Status obrigatorio.")
    except ValidationError as exc:
        return HttpResponseBadRequest(exc.messages[0])
    return render(request, "engineering/partials/task_card.html", {"task": task})
