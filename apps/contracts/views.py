from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.billing.services import require_access
from apps.legal.services import audit, can_write, visible_matters
from apps.legal.views import organization_required
from .catalog import EXAMPLE_BODY, EXAMPLE_TITLE, VARIABLES
from .forms import BuildContractForm, ContractTemplateForm
from .models import ContractTemplate
from .services import can_manage_templates, generate_revision, visible_contracts, visible_revisions


def contracts_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require_access(request.organization, advanced=True)
        from apps.core.services import member_has_module
        if not member_has_module(getattr(request, "membership", None), "contracts"):
            raise PermissionDenied("Acesso ao módulo de contratos restrito para o seu usuário.")
        return view(request, *args, **kwargs)
    return organization_required(wrapped)


def context(request, **extra):
    return {
        "page_title": "Montagem de contratos", "active_nav": "contracts",
        "can_manage_templates": can_manage_templates(request.user, request.organization),
        "can_build": can_write(request.user, request.organization),
        "variables": [{"key": key, "label": item[0], "group": item[1], "token": "[[" + key + "]]"} for key, item in VARIABLES.items()],
        **extra,
    }


@require_GET
@contracts_access
def library(request):
    templates = ContractTemplate.objects.filter(organization=request.organization)
    if not can_manage_templates(request.user, request.organization):
        templates = templates.filter(is_active=True)
    return render(request, "contracts/library.html", context(request,
        templates=templates, recent=visible_contracts(request.user, request.organization).select_related("client", "matter")[:6],
    ))


@require_http_methods(["GET", "POST"])
@contracts_access
def template_edit(request, pk=None):
    if not can_manage_templates(request.user, request.organization):
        raise PermissionDenied("Somente a direção e a gestão podem configurar os modelos.")
    instance = get_object_or_404(ContractTemplate, pk=pk, organization=request.organization) if pk else ContractTemplate(organization=request.organization, created_by=request.user)
    initial = {"name": EXAMPLE_TITLE, "body": EXAMPLE_BODY, "description": "Base inicial editável. Revise as cláusulas para o caso concreto."} if request.GET.get("exemplo") == "1" and not pk else None
    form = ContractTemplateForm(request.POST if request.method == "POST" else None, instance=instance, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            template = form.save()
            audit(organization=request.organization, actor=request.user, action="contract.template_updated" if pk else "contract.template_created", obj=template,
                  description="Modelo atualizado; contratos anteriores mantêm suas versões.")
        messages.success(request, "Modelo salvo. Os contratos já gerados foram preservados.")
        return redirect("contracts:library")
    return render(request, "contracts/template_form.html", context(request, form=form, template=instance))


@require_POST
@contracts_access
def template_archive(request, pk):
    if not can_manage_templates(request.user, request.organization):
        raise PermissionDenied("Somente a direção e a gestão podem arquivar modelos.")
    with transaction.atomic():
        template = get_object_or_404(ContractTemplate.objects.select_for_update(), pk=pk, organization=request.organization)
        template.is_active = False
        template.save()
        audit(organization=request.organization, actor=request.user, action="contract.template_archived", obj=template, description="Modelo arquivado para preservar o histórico.")
    messages.success(request, "Modelo arquivado. As versões dos contratos continuam disponíveis.")
    return redirect("contracts:library")


@require_GET
@contracts_access
def history(request):
    contracts = visible_contracts(request.user, request.organization).select_related("matter", "client", "template").annotate(version_count=Count("revisions")).order_by("-created_at", "-pk")
    from django.core.paginator import Paginator
    page = Paginator(contracts, 24).get_page(request.GET.get("page"))
    return render(request, "contracts/history.html", context(request, page=page))


@require_http_methods(["GET", "POST"])
@contracts_access
def build(request, template_pk=None, contract_pk=None):
    if not can_write(request.user, request.organization):
        raise PermissionDenied("Seu perfil permite somente consulta de contratos gerados.")
    contract = get_object_or_404(visible_contracts(request.user, request.organization).select_related("template", "matter", "client"), pk=contract_pk) if contract_pk else None
    template = contract.template if contract else get_object_or_404(ContractTemplate, pk=template_pk, organization=request.organization, is_active=True)
    selected_matter = None
    if not contract and request.GET.get("pasta"):
        try:
            matter_pk = int(request.GET["pasta"])
        except (TypeError, ValueError):
            matter_pk = 0
        selected_matter = get_object_or_404(visible_matters(request.user, request.organization).select_related("client"), pk=matter_pk)
    form = BuildContractForm(request.POST if request.method == "POST" else None, actor=request.user, organization=request.organization, template=template, contract=contract, selected_matter=selected_matter)
    preview = None
    if request.method == "POST" and form.is_valid():
        preview = form.cleaned_data["rendered_text"]
        if request.POST.get("action") == "generate":
            if not form.cleaned_data["reviewed"]:
                form.add_error("reviewed", "Confira os dados e marque a revisão antes de gerar a versão.")
            else:
                try:
                    revision = generate_revision(
                        actor=request.user, organization=request.organization, template=template, contract=contract,
                        matter=form.cleaned_data["matter"], client=form.cleaned_data["client"], title=form.cleaned_data["title"],
                        source_body=form.cleaned_data["source_body"], values=form.cleaned_data["values"],
                        operation_key=form.cleaned_data["operation_key"],
                    )
                except ValidationError as error:
                    form.add_error(None, error)
                else:
                    messages.success(request, f"Versão {revision.number} preservada e vinculada à pasta. O arquivo DOCX já está disponível.")
                    return redirect("contracts:detail", pk=revision.contract_id)
    matters = list(visible_matters(request.user, request.organization).values("id", "title", "client_id"))
    contacts = list(form.fields["client"].queryset.values("id", "name", "document", "email", "phone"))
    return render(request, "contracts/build.html", context(request, form=form, template=template, contract=contract, preview=preview, fill_data={"matters": matters, "contacts": contacts}))


@require_GET
@contracts_access
def detail(request, pk):
    contract = get_object_or_404(visible_contracts(request.user, request.organization).select_related("matter", "client", "template"), pk=pk)
    revisions = contract.revisions.select_related("created_by", "document_version")
    revision = revisions.first()
    if request.GET.get("versao"):
        try:
            number = int(request.GET["versao"])
        except ValueError:
            number = 0
        revision = get_object_or_404(revisions, number=number)
    return render(request, "contracts/detail.html", context(request, contract=contract, revision=revision, revisions=revisions))


@require_GET
@contracts_access
def print_revision(request, pk):
    revision = get_object_or_404(visible_revisions(request.user, request.organization).select_related("contract", "document_version"), pk=pk)
    response = render(request, "contracts/print.html", {"revision": revision})
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "default-src 'none'; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
@contracts_access
def download(request, pk):
    revision = get_object_or_404(visible_revisions(request.user, request.organization).select_related("document_version"), pk=pk)
    response = FileResponse(revision.document_version.file.open("rb"), as_attachment=True, filename=f"contrato-{revision.contract_id}-v{revision.number}.docx", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    audit(organization=request.organization, actor=request.user, action="contract.downloaded", obj=revision, description=f"Download da versão {revision.number}.")
    return response
