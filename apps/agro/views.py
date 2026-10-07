from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core.branding import process_branding_form
from apps.core.navigation import SEGMENT_APPS, app_shell_context
from apps.core.services import require_business_organization, require_permission, transition
from apps.core.team import team_management_context

from .forms import AgroFinanceEntryForm, AgroPurchaseForm, FarmForm, FarmOperationForm, FieldForm, InventoryItemForm, StaffMemberForm, SupplierForm
from .models import AgroFinanceEntry, AgroPurchase, Farm, FarmOperation, Field, InventoryItem, StaffMember, Supplier


OPERATION_TRANSITIONS = {
    FarmOperation.Status.PLANNED: {FarmOperation.Status.RUNNING},
    FarmOperation.Status.RUNNING: {
        FarmOperation.Status.PLANNED,
        FarmOperation.Status.REVIEW,
        FarmOperation.Status.DONE,
    },
    FarmOperation.Status.REVIEW: {FarmOperation.Status.RUNNING, FarmOperation.Status.DONE},
    FarmOperation.Status.DONE: {FarmOperation.Status.RUNNING},
}


@login_required
def workspace(request, section="overview"):
    if settings.JUMBI_LEGAL_ONLY:
        return redirect("office:workspace")
    shell_context = app_shell_context("agro", section)
    if shell_context is None:
        raise Http404("Módulo agro não encontrado.")
    organization = require_business_organization(
        request, SEGMENT_APPS["agro"]["business_type"]
    )

    def redirect_to_section():
        if section == "overview":
            return redirect("agro:workspace")
        return redirect("agro:section", section=section)

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

    farm_form = FarmForm(prefix="farm")
    field_form = FieldForm(prefix="field", organization=organization)
    staff_form = StaffMemberForm(prefix="staff", organization=organization)
    supplier_form = SupplierForm(prefix="supplier")
    inventory_form = InventoryItemForm(prefix="inventory")
    operation_form = FarmOperationForm(prefix="operation", organization=organization)
    finance_form = AgroFinanceEntryForm(prefix="finance", organization=organization)
    purchase_form = AgroPurchaseForm(prefix="purchase", organization=organization)
    if request.method == "POST":
        if request.POST.get("action") == "farm":
            require_permission(request.user, "agro.add_farm", organization)
            farm_form = FarmForm(request.POST, prefix="farm")
            if farm_form.is_valid():
                farm = farm_form.save(commit=False)
                farm.organization = organization
                farm.save()
                messages.success(request, "Fazenda cadastrada no Agro.")
                return redirect_to_section()
        elif request.POST.get("action") == "field":
            require_permission(request.user, "agro.add_field", organization)
            field_form = FieldForm(request.POST, prefix="field", organization=organization)
            if field_form.is_valid():
                field = field_form.save()
                messages.success(request, f"Talhao {field.name} cadastrado no Agro.")
                return redirect_to_section()
        elif request.POST.get("action") == "staff":
            require_permission(request.user, "agro.add_staff", organization)
            staff_form = StaffMemberForm(request.POST, prefix="staff", organization=organization)
            if staff_form.is_valid():
                staff = staff_form.save(commit=False)
                staff.organization = organization
                staff.save()
                messages.success(request, "Funcionario rural cadastrado.")
                return redirect_to_section()
        elif request.POST.get("action") == "supplier":
            require_permission(request.user, "agro.add_supplier", organization)
            supplier_form = SupplierForm(request.POST, prefix="supplier")
            if supplier_form.is_valid():
                supplier = supplier_form.save(commit=False)
                supplier.organization = organization
                supplier.save()
                messages.success(request, "Fornecedor agro cadastrado.")
                return redirect_to_section()
        elif request.POST.get("action") == "inventory":
            require_permission(request.user, "agro.add_inventory", organization)
            inventory_form = InventoryItemForm(request.POST, prefix="inventory")
            if inventory_form.is_valid():
                item = inventory_form.save(commit=False)
                item.organization = organization
                item.save()
                messages.success(request, "Insumo cadastrado no estoque.")
                return redirect_to_section()
        elif request.POST.get("action") == "operation":
            require_permission(request.user, "agro.add_operation", organization)
            operation_form = FarmOperationForm(request.POST, prefix="operation", organization=organization)
            if operation_form.is_valid():
                operation = operation_form.save(commit=False)
                operation.organization = organization
                operation.save()
                messages.success(request, "Operacao agricola registrada.")
                return redirect_to_section()
        elif request.POST.get("action") == "finance":
            require_permission(request.user, "agro.add_finance", organization)
            finance_form = AgroFinanceEntryForm(request.POST, prefix="finance", organization=organization)
            if finance_form.is_valid():
                entry = finance_form.save(commit=False)
                entry.organization = organization
                entry.save()
                messages.success(request, "Lancamento financeiro registrado.")
                return redirect_to_section()
        elif request.POST.get("action") == "purchase":
            require_permission(request.user, "agro.add_purchase", organization)
            purchase_form = AgroPurchaseForm(request.POST, prefix="purchase", organization=organization)
            if purchase_form.is_valid():
                purchase = purchase_form.save(commit=False)
                purchase.organization = organization
                purchase.save()
                messages.success(request, "Compra agro registrada.")
                return redirect_to_section()
    farms = Farm.objects.filter(organization=organization)
    fields = Field.objects.filter(farm__organization=organization).select_related("farm")
    finance_entries = AgroFinanceEntry.objects.filter(organization=organization).select_related("farm", "field")
    context = {
        **shell_context,
        **branding_context,
        **team_context,
        "organization": organization,
        "farm_form": farm_form,
        "field_form": field_form,
        "staff_form": staff_form,
        "supplier_form": supplier_form,
        "inventory_form": inventory_form,
        "operation_form": operation_form,
        "finance_form": finance_form,
        "purchase_form": purchase_form,
        "farms": farms,
        "fields": fields,
        "staff_members": StaffMember.objects.filter(organization=organization).select_related("farm"),
        "suppliers": Supplier.objects.filter(organization=organization),
        "inventory_items": InventoryItem.objects.filter(organization=organization),
        "operations": FarmOperation.objects.filter(organization=organization).select_related("farm", "field", "responsible"),
        "finance_entries": finance_entries[:8],
        "purchases": AgroPurchase.objects.filter(organization=organization).select_related("supplier", "item")[:8],
        "total_area": sum((farm.total_area_hectares for farm in farms), start=0),
        "open_operations": FarmOperation.objects.filter(organization=organization).exclude(status=FarmOperation.Status.DONE).count(),
        "low_stock": sum(1 for item in InventoryItem.objects.filter(organization=organization) if item.needs_restock),
        "finance_balance": sum((entry.amount if entry.kind == AgroFinanceEntry.Kind.REVENUE else -entry.amount for entry in finance_entries), start=0),
    }
    return render(request, "agro/workspace.html", context)


@login_required
@require_POST
def operation_status(request, pk):
    if settings.JUMBI_LEGAL_ONLY:
        return redirect("office:workspace")
    organization = require_business_organization(
        request, SEGMENT_APPS["agro"]["business_type"]
    )
    operation = FarmOperation.objects.filter(organization=organization, pk=pk).first()
    if operation is None:
        return HttpResponseBadRequest("Operação não encontrada para a organização ativa.")
    try:
        transition(
            instance=operation,
            target_status=request.POST["status"],
            actor=request.user,
            permission="agro.change_operation_status",
            transition_map=OPERATION_TRANSITIONS,
        )
    except KeyError:
        return HttpResponseBadRequest("Status obrigatório.")
    except ValidationError as exc:
        return HttpResponseBadRequest(exc.messages[0])
    return redirect("agro:section", section="operations")
