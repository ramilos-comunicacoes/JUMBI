"""Authenticated, organization-scoped screens for the legal workspace."""

import hashlib
import json
import tempfile
import zipfile
from decimal import Decimal
from functools import wraps
from pathlib import Path
from uuid import UUID

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import CharField, Q
from django.db.models.functions import Cast
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.models import Membership
from .forms import (
    MODULE_FORMS, DeadlineConfirmationForm, DeadlineFulfillmentForm,
    DocumentUploadForm, PaymentForm, PaymentReversalForm, ReasonForm,
    TaskCompletionForm,
)
from .models import (
    Appointment, AuditEvent, Contact, CourtCase, Deadline, DeadlineRevision,
    Document, DocumentVersion, FinanceEntry, Matter, Opportunity, Payment, Task,
)
from .services import (
    add_document_version, audit, complete_task, confirm_deadline,
    fulfill_deadline, record_payment, reverse_payment, revise_deadline,
    visible_matters,
)


MODULES = {
    "matters": {"model": Matter, "title": "Pastas jurídicas", "singular": "pasta", "subtitle": "O trabalho do escritório, do primeiro atendimento à conclusão.", "columns": ["Pasta", "Cliente", "Natureza", "Responsável", "Situação"], "search": ["title", "client__name", "area"], "status": "status"},
    "contacts": {"model": Contact, "title": "Pessoas", "singular": "pessoa", "subtitle": "Um cadastro, todas as relações do escritório.", "columns": ["Nome", "Tipo", "CPF / CNPJ", "E-mail", "Telefone"], "search": ["name", "email", "document", "phone"], "status": "kind"},
    "cases": {"model": CourtCase, "title": "Processos", "singular": "processo", "subtitle": "Processos judiciais e administrativos vinculados às pastas.", "columns": ["Número", "Pasta", "Tribunal / órgão", "Parte contrária"], "search": ["number", "court", "matter__title", "opposing_party"]},
    "tasks": {"model": Task, "title": "Tarefas", "singular": "tarefa", "subtitle": "Responsabilidade, prioridades e evidências de cada entrega.", "columns": ["Tarefa", "Pasta", "Responsável", "Entrega", "Prioridade", "Situação"], "search": ["title", "description", "matter__title"], "status": "status"},
    "deadlines": {"model": Deadline, "title": "Prazos e controladoria", "singular": "prazo", "subtitle": "Conferência humana e histórico das obrigações jurídicas.", "columns": ["Obrigação", "Pasta", "Responsável", "Vencimento", "Situação"], "search": ["title", "source", "matter__title"], "status": "status"},
    "appointments": {"model": Appointment, "title": "Agenda", "singular": "compromisso", "subtitle": "Audiências, reuniões e compromissos da equipe.", "columns": ["Compromisso", "Pasta", "Início", "Término", "Local", "Responsável"], "search": ["title", "location", "matter__title"]},
    "documents": {"model": Document, "title": "Documentos", "singular": "documento", "subtitle": "Arquivos privados, versões preservadas e acesso autorizado.", "columns": ["Documento", "Pasta", "Classificação", "Versão", "Incluído em"], "search": ["title", "kind", "matter__title"]},
    "finance": {"model": FinanceEntry, "title": "Financeiro", "singular": "lançamento", "subtitle": "Previsões, baixas e valores de clientes com saldos conferíveis.", "columns": ["Descrição", "Pasta", "Tipo", "Previsto", "Movimentado", "Saldo", "Vencimento"], "search": ["description", "matter__title"], "status": "kind"},
    "crm": {"model": Opportunity, "title": "Relacionamento", "singular": "oportunidade", "subtitle": "Pessoas, oportunidades e a próxima ação de cada atendimento.", "columns": ["Oportunidade", "Pessoa", "Etapa", "Estimativa", "Responsável", "Próxima ação"], "search": ["title", "contact__name", "next_action"], "status": "stage"},
}


def organization_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse("core:login"))
        organization = getattr(request, "organization", None)
        if organization is None:
            raise PermissionDenied("Seu usuário não possui um escritório ativo selecionado.")
        membership = Membership.objects.filter(
            user=request.user, organization=organization, is_active=True,
            organization__status="active", organization__business_type="office",
        ).first()
        if membership is None:
            raise PermissionDenied("O acesso a este escritório não está ativo.")
        request.membership = membership
        return view(request, *args, **kwargs)
    return wrapped


def can_manage_finance(request):
    from apps.billing.services import has_advanced
    return request.membership.role in {"owner", "manager"} and has_advanced(request.organization)


def can_edit(request):
    return request.membership.role in {"owner", "manager", "operator"}


def get_module(request, module, *, write=False):
    if module not in MODULES:
        raise Http404("Módulo não encontrado.")
    if module == "finance" and not can_manage_finance(request):
        raise PermissionDenied("O financeiro está disponível aos perfis de direção e gestão.")
    if write and not can_edit(request):
        raise PermissionDenied("Seu perfil permite somente consulta.")
    return MODULES[module]


def scoped_queryset(user, organization, model, *, for_export=False):
    from apps.contracts.models import Contract, ContractRevision, ContractTemplate
    from apps.contracts.services import visible_contracts, visible_revisions
    from apps.performance.models import Goal, GoalUpdate
    from apps.performance.services import visible_goals

    role = Membership.objects.filter(user=user, organization=organization, is_active=True, user__is_active=True, organization__status="active").values_list("role", flat=True).first()
    if role is None:
        return model.objects.none()
    if model is Contract:
        return visible_contracts(user, organization)
    if model is ContractRevision:
        return visible_revisions(user, organization)
    if model is ContractTemplate:
        templates = ContractTemplate.objects.filter(organization=organization)
        if role not in {"owner", "manager"}:
            permitted_templates = Q(is_active=True)
            if for_export:
                permitted_templates |= Q(pk__in=visible_contracts(user, organization).values("template_id"))
            templates = templates.filter(permitted_templates)
        return templates
    if model in {Goal, GoalUpdate}:
        if for_export:
            # Portability keeps historical financial goals available to the
            # same roles as financial entries, even after plan expiration.
            goals = Goal.objects.filter(organization=organization)
            if role not in {"owner", "manager"}:
                goals = goals.exclude(metric=Goal.Metric.REVENUE)
        else:
            goals = visible_goals(user, organization)
        return goals if model is Goal else GoalUpdate.objects.filter(organization=organization, goal__in=goals)
    matters = visible_matters(user, organization)
    queryset = model.objects.filter(organization=organization)
    if model is Matter:
        return matters
    fields = {field.name for field in model._meta.fields}
    if "matter" in fields:
        return queryset.filter(Q(matter__in=matters) | Q(matter__isnull=True))
    if model is DocumentVersion:
        return queryset.filter(document__matter__in=matters, document__organization=organization)
    if model is DeadlineRevision:
        return queryset.filter(deadline__matter__in=matters, deadline__organization=organization)
    if model is Payment:
        return queryset.filter(entry__in=scoped_queryset(user, organization, FinanceEntry, for_export=for_export))
    return queryset


def accessible_audit(user, organization, role=None, *, for_export=False):
    """Only audit events whose current subject is still authorized are visible."""
    role = Membership.objects.filter(user=user, organization=organization, is_active=True, user__is_active=True, organization__status="active").values_list("role", flat=True).first()
    if role is None:
        return AuditEvent.objects.none()
    from apps.contracts.models import Contract, ContractRevision, ContractTemplate
    from apps.performance.models import Goal, GoalUpdate
    models = [Matter, Contact, CourtCase, Task, Deadline, DeadlineRevision, Appointment, Document, DocumentVersion, Opportunity, ContractTemplate, Contract, ContractRevision, Goal, GoalUpdate]
    if role in {"owner", "manager"}:
        models.extend([FinanceEntry, Payment])
    global_events = Q(object_type="core.organization", object_id=str(organization.pk), action__in=["workspace.created", "team.invited", "team.revoked", "team.invitation_revoked", "team.accepted", "workspace.exported"])
    permitted = global_events if role in {"owner", "manager"} else global_events & Q(actor=user)
    for model in models:
        ids = scoped_queryset(user, organization, model, for_export=for_export).annotate(
            audit_id=Cast("pk", output_field=CharField())
        ).values("audit_id")
        permitted |= Q(object_type=model._meta.label_lower, object_id__in=ids)
    return AuditEvent.objects.filter(organization=organization).filter(permitted).select_related("actor")


def user_label(user):
    return (user.get_full_name() or user.email) if user else "—"


def date_label(value):
    if value is None:
        return "—"
    if hasattr(value, "hour"):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d/%m/%Y %H:%M")
    return value.strftime("%d/%m/%Y")


def money_label(value):
    return "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def record_actions(request, module, obj):
    actions = []
    if module == "documents":
        version = obj.latest_version
        if version:
            actions.append({"label": "Baixar", "url": reverse("legal:document_download", args=[version.pk])})
        if can_edit(request):
            actions.append({"label": "Nova versão", "url": reverse("legal:document_upload", args=[obj.pk])})
    if not can_edit(request):
        return actions
    names = []
    if module == "tasks":
        if obj.status == Task.Status.TODO:
            names.append(("start", "Iniciar"))
        if obj.status != Task.Status.DONE:
            names.append(("complete", "Concluir"))
        else:
            names.append(("reopen", "Reabrir"))
    elif module == "deadlines":
        if obj.status == Deadline.Status.PENDING:
            names.append(("confirm", "Conferir"))
        elif obj.status == Deadline.Status.CONFIRMED:
            names.append(("fulfill", "Registrar cumprimento"))
    elif module == "finance" and can_manage_finance(request):
        if obj.balance > 0:
            names.append(("payment", "Registrar baixa"))
        if obj.payments.filter(reversal_of__isnull=True, reversal__isnull=True).exists():
            names.append(("reverse", "Estornar baixa"))
    actions.extend({"label": label, "url": reverse("legal:action", args=[module, obj.pk, name])} for name, label in names)
    return actions


def table_row(request, module, obj):
    matter = getattr(obj, "matter", None)
    matter_title = str(matter) if matter else "—"
    if module == "matters":
        cells = [obj.title, str(obj.client) if obj.client else "—", obj.get_nature_display(), user_label(obj.owner), obj.get_status_display()]
    elif module == "contacts":
        cells = [obj.name, obj.get_kind_display(), obj.document or "—", obj.email or "—", obj.phone or "—"]
    elif module == "cases":
        cells = [obj.number, matter_title, obj.court or "—", obj.opposing_party or "—"]
    elif module == "tasks":
        cells = [obj.title, matter_title, user_label(obj.owner), date_label(obj.due_date), obj.get_priority_display(), obj.get_status_display()]
    elif module == "deadlines":
        cells = [obj.title, matter_title, user_label(obj.owner), date_label(obj.due_date), obj.get_status_display()]
    elif module == "appointments":
        cells = [obj.title, matter_title, date_label(obj.starts_at), date_label(obj.ends_at), obj.location or "—", user_label(obj.owner)]
    elif module == "documents":
        version = obj.latest_version
        cells = [obj.title, matter_title, obj.kind, f"v{version.number}" if version else "Sem arquivo", date_label(obj.created_at)]
    elif module == "finance":
        cells = [obj.description, matter_title, obj.get_kind_display(), money_label(obj.amount), money_label(obj.paid_amount), money_label(obj.balance), date_label(obj.due_date)]
    else:
        cells = [obj.title, str(obj.contact), obj.get_stage_display(), money_label(obj.amount), user_label(obj.owner), obj.next_action or "—"]
    url = reverse("legal:detail", args=[obj.pk]) if module == "matters" else (reverse("legal:detail", args=[matter.pk]) if matter else "")
    return {"cells": cells, "url": url, "edit_url": reverse("legal:edit", args=[module, obj.pk]) if can_edit(request) else "", "actions": record_actions(request, module, obj)}


def optimize_queryset(queryset, model):
    related = [f.name for f in model._meta.fields if f.is_relation and f.name != "organization"]
    if related:
        queryset = queryset.select_related(*related)
    if model is Document:
        queryset = queryset.prefetch_related("versions")
    return queryset


@organization_required
@require_GET
def dashboard(request):
    from .dashboard_views import overview
    return overview(request)


@organization_required
@require_GET
def record_list(request, module):
    config = get_module(request, module)
    queryset = scoped_queryset(request.user, request.organization, config["model"])
    from .niches import filter_niche, niche_selection
    niche, niche_choices = niche_selection(request)
    if config["model"] is Matter:
        queryset = filter_niche(queryset, niche, niche_choices)
    elif "matter" in {field.name for field in config["model"]._meta.fields}:
        queryset = filter_niche(queryset, niche, niche_choices, relation="matter__")
    elif niche and module in {"contacts", "crm"}:
        clients = filter_niche(visible_matters(request.user, request.organization), niche, niche_choices).values("client_id")
        queryset = queryset.filter(**{"pk__in" if module == "contacts" else "contact_id__in": clients})
    q = request.GET.get("q", "").strip()[:200]
    if q:
        search = Q()
        for field in config["search"]:
            search |= Q(**{f"{field}__icontains": q})
        queryset = queryset.filter(search)
    status_field = config.get("status")
    status_choices = list(config["model"]._meta.get_field(status_field).choices) if status_field else []
    status = request.GET.get("status", "")
    if status and status in dict(status_choices):
        queryset = queryset.filter(**{status_field: status})
    else:
        status = ""
    page_obj = Paginator(optimize_queryset(queryset, config["model"]), 25).get_page(request.GET.get("page"))
    return render(request, "legal/list.html", {
        "module": module, "active_nav": module, "title": config["title"], "page_title": config["title"], "subtitle": config["subtitle"], "description": config["subtitle"],
        "columns": config["columns"], "rows": [table_row(request, module, obj) for obj in page_obj],
        "page_obj": page_obj, "q": q, "status": status, "status_choices": status_choices,
        "niche": niche, "niche_choices": niche_choices,
        "create_url": reverse("legal:create", args=[module]), "can_create": can_edit(request), "export_url": reverse("legal:export"),
    })


def add_validation_errors(form, error):
    if hasattr(error, "message_dict"):
        for name, values in error.message_dict.items():
            for value in values:
                form.add_error(name if name in form.fields else None, value)
    else:
        for value in error.messages:
            form.add_error(None, value)


def render_form(request, *, title, form, module, cancel_url, submit_label="Salvar", subtitle=""):
    return render(request, "legal/form.html", {
        "title": title, "page_title": title, "subtitle": subtitle, "form": form,
        "active_nav": module, "module": module, "cancel_url": cancel_url,
        "submit_label": submit_label, "is_multipart": form.is_multipart(),
    })


@organization_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def record_form(request, module, pk=None):
    config = get_module(request, module, write=True)
    instance = None
    if pk:
        if not scoped_queryset(request.user, request.organization, config["model"]).filter(pk=pk).exists():
            raise Http404("Registro não encontrado.")
        queryset = config["model"].objects.filter(organization=request.organization)
        if request.method == "POST":
            queryset = queryset.select_for_update()
        instance = get_object_or_404(queryset, pk=pk)
        if not scoped_queryset(request.user, request.organization, config["model"]).filter(pk=pk).exists():
            raise Http404("Registro não encontrado.")
    previous_due_date = instance.due_date if isinstance(instance, Deadline) else None
    initial = {"owner": request.user.pk}
    if request.GET.get("matter"):
        try:
            matter_id = int(request.GET["matter"])
        except (TypeError, ValueError):
            raise Http404("Pasta não encontrada.") from None
        initial["matter"] = get_object_or_404(visible_matters(request.user, request.organization), pk=matter_id).pk
    form = MODULE_FORMS[module](
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=instance, initial=initial, organization=request.organization, user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                obj = form.save(commit=False)
                previous_owner_id = None
                if pk:
                    # Preserve transitions performed after this form was opened.
                    # In particular, editing a task must not undo completion,
                    # and a financial edit shares the lock used by payments.
                    # Keep DISTINCT permission subqueries out of FOR UPDATE;
                    # PostgreSQL does not allow locking a DISTINCT result.
                    current = get_object_or_404(config["model"].objects.select_for_update().filter(organization=request.organization), pk=pk)
                    if not scoped_queryset(request.user, request.organization, config["model"]).filter(pk=pk).exists():
                        raise Http404("Registro não encontrado.")
                    previous_owner_id = getattr(current, "owner_id", None)
                    if isinstance(current, Deadline):
                        previous_due_date = current.due_date
                    for name in form._meta.fields:
                        field = obj._meta.get_field(name)
                        if name in form.cleaned_data and not field.many_to_many and not form.fields[name].disabled:
                            setattr(current, name, getattr(obj, name))
                    obj = current
                    form.instance = current
                obj.organization = request.organization
                if isinstance(obj, Matter):
                    from apps.billing.services import check_capacity
                    check_capacity(request.organization, "matters", instance=obj)
                if isinstance(obj, Deadline) and pk:
                    new_date = obj.due_date
                    obj.due_date = previous_due_date
                    obj.save()
                    if new_date != previous_due_date:
                        obj = revise_deadline(deadline=obj, actor=request.user, due_date=new_date, reason=form.cleaned_data["change_reason"])
                else:
                    obj.save()
                form.save_m2m()
                audit(organization=request.organization, actor=request.user, action="record.updated" if pk else "record.created", obj=obj, description=f"{'Atualização' if pk else 'Cadastro'} de {config['singular']}.")
                if pk and previous_owner_id is not None and previous_owner_id != getattr(obj, "owner_id", None):
                    audit(organization=request.organization, actor=request.user, action="record.reassigned", obj=obj, description=f"Responsável alterado do usuário #{previous_owner_id} para o usuário #{obj.owner_id}.")
                if isinstance(obj, Document) and not pk:
                    add_document_version(document=obj, actor=request.user, file=form.cleaned_data["file"])
            messages.success(request, "Alterações salvas." if pk else "Registro criado.")
            if isinstance(obj, Matter):
                return redirect("legal:detail", pk=obj.pk)
            return redirect("legal:list", module=module)
        except ValidationError as error:
            add_validation_errors(form, error)
    title = f"Editar {config['singular']}" if pk else f"Nova {config['singular']}" if module in {"matters", "contacts", "tasks", "crm"} else f"Novo {config['singular']}"
    return render_form(request, title=title, form=form, module=module, cancel_url=reverse("legal:list", args=[module]), subtitle=config["subtitle"])


@organization_required
@require_GET
def matter_detail(request, pk):
    matter = get_object_or_404(visible_matters(request.user, request.organization).select_related("client", "owner"), pk=pk)
    context = {
        "title": matter.title, "page_title": matter.title, "active_nav": "matters", "matter": matter,
        "can_edit": can_edit(request), "can_manage_finance": can_manage_finance(request), "can_manage": can_manage_finance(request),
        "create_links": {module: reverse("legal:create", args=[module]) + f"?matter={matter.pk}" for module in ("tasks", "deadlines", "cases", "appointments", "documents", "finance")},
    }
    for key, model in [("tasks", Task), ("deadlines", Deadline), ("cases", CourtCase), ("appointments", Appointment), ("documents", Document)]:
        context[key] = optimize_queryset(scoped_queryset(request.user, request.organization, model).filter(matter=matter), model)
    context["finance_entries"] = scoped_queryset(request.user, request.organization, FinanceEntry).filter(matter=matter) if can_manage_finance(request) else FinanceEntry.objects.none()
    related_events = Q(object_type=Matter._meta.label_lower, object_id=str(matter.pk))
    for model, relation in [(Task, "matter"), (Deadline, "matter"), (CourtCase, "matter"), (Appointment, "matter"), (Document, "matter"), (DocumentVersion, "document__matter"), (DeadlineRevision, "deadline__matter"), (FinanceEntry, "matter"), (Payment, "entry__matter")]:
        ids = model.objects.filter(organization=request.organization, **{relation: matter}).annotate(audit_id=Cast("pk", output_field=CharField())).values("audit_id")
        related_events |= Q(object_type=model._meta.label_lower, object_id__in=ids)
    context["activity"] = accessible_audit(request.user, request.organization, request.membership.role).filter(related_events)[:12]
    return render(request, "legal/matter_detail.html", context)


@organization_required
@require_http_methods(["GET", "POST"])
def record_action(request, module, pk, action):
    config = get_module(request, module, write=True)
    obj = get_object_or_404(scoped_queryset(request.user, request.organization, config["model"]), pk=pk)
    action_forms = {
        ("tasks", "start"): (ReasonForm, "Iniciar tarefa", "Iniciar"),
        ("tasks", "complete"): (TaskCompletionForm, "Concluir tarefa", "Registrar conclusão"),
        ("tasks", "reopen"): (ReasonForm, "Reabrir tarefa", "Reabrir"),
        ("deadlines", "confirm"): (DeadlineConfirmationForm, "Conferir prazo", "Confirmar conferência"),
        ("deadlines", "fulfill"): (DeadlineFulfillmentForm, "Registrar cumprimento", "Registrar cumprimento"),
        ("finance", "payment"): (PaymentForm, "Registrar baixa", "Registrar baixa"),
        ("finance", "reverse"): (PaymentReversalForm, "Estornar baixa", "Registrar estorno"),
    }
    if (module, action) not in action_forms:
        raise Http404("Ação não encontrada.")
    form_class, title, submit_label = action_forms[(module, action)]
    form = form_class(request.POST if request.method == "POST" else None, initial={"date": timezone.localdate()})
    if action == "reverse":
        form.fields["payment"].queryset = Payment.objects.filter(organization=request.organization, entry=obj, reversal_of__isnull=True, reversal__isnull=True)
        form.fields["payment"].label_from_instance = lambda payment: f"{date_label(payment.date)} — {money_label(payment.amount)} — {payment.note}"
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                if module == "tasks":
                    if action == "complete":
                        complete_task(task=obj, actor=request.user, evidence=data["evidence"])
                    else:
                        obj = Task.objects.select_for_update().get(pk=obj.pk, organization=request.organization)
                        if action == "start" and obj.status != Task.Status.TODO:
                            raise ValidationError("Somente uma tarefa a fazer pode ser iniciada.")
                        if action == "reopen" and obj.status != Task.Status.DONE:
                            raise ValidationError("Somente uma tarefa concluída pode ser reaberta.")
                        obj.status = Task.Status.DOING if action == "start" else Task.Status.TODO
                        obj.completed_at = None
                        obj.completion_note = ""
                        obj.save()
                        audit(organization=request.organization, actor=request.user, action=f"task.{action}", obj=obj, description=data["reason"])
                elif module == "deadlines":
                    if action == "confirm":
                        confirm_deadline(deadline=obj, actor=request.user)
                    else:
                        fulfill_deadline(deadline=obj, actor=request.user, evidence=data["evidence"])
                elif action == "payment":
                    record_payment(entry=obj, actor=request.user, amount=data["amount"], date=data["date"], note=data["note"], operation_key=data["operation_key"])
                else:
                    reverse_payment(payment=data["payment"], actor=request.user, note=data["reason"])
            messages.success(request, "Ação registrada no histórico.")
            return redirect("legal:list", module=module)
        except ValidationError as error:
            add_validation_errors(form, error)
    return render_form(request, title=title, form=form, module=module, cancel_url=reverse("legal:list", args=[module]), submit_label=submit_label, subtitle=str(obj))


@organization_required
@require_GET
def document_download(request, pk):
    version = get_object_or_404(scoped_queryset(request.user, request.organization, DocumentVersion).select_related("document"), pk=pk)
    try:
        source = version.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("O arquivo não está disponível. Contate a administração do escritório.") from None
    audit(organization=request.organization, actor=request.user, action="document.downloaded", obj=version, description=f"Download da versão {version.number}.")
    response = FileResponse(source, as_attachment=True, filename=version.original_name)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@organization_required
@require_http_methods(["GET", "POST"])
def document_upload(request, pk):
    get_module(request, "documents", write=True)
    document = get_object_or_404(scoped_queryset(request.user, request.organization, Document), pk=pk)
    form = DocumentUploadForm(request.POST if request.method == "POST" else None, request.FILES if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            add_document_version(document=document, actor=request.user, file=form.cleaned_data["file"])
            messages.success(request, "Nova versão incluída. As versões anteriores foram preservadas.")
            return redirect("legal:detail", pk=document.matter_id)
        except ValidationError as error:
            add_validation_errors(form, error)
    return render_form(request, title="Enviar nova versão", form=form, module="documents", cancel_url=reverse("legal:detail", args=[document.matter_id]), submit_label="Enviar versão", subtitle=document.title)


from apps.contracts.models import Contract, ContractRevision, ContractTemplate
from apps.performance.models import Goal, GoalUpdate


EXPORT_FIELDS = {
    Matter: ["title", "client_id", "nature", "area", "status", "description", "confidential", "owner_id", "created_at"],
    Contact: ["name", "email", "phone", "document", "kind", "birth_date", "created_at"],
    CourtCase: ["matter_id", "number", "court", "opposing_party", "notes", "created_at"],
    Task: ["matter_id", "title", "description", "owner_id", "due_date", "status", "priority", "completion_note", "completed_at", "created_at"],
    Deadline: ["matter_id", "title", "source", "due_date", "owner_id", "status", "confirmed_by_id", "confirmed_at", "evidence", "created_at"],
    DeadlineRevision: ["deadline_id", "previous_date", "new_date", "reason", "actor_id", "created_at"],
    Appointment: ["matter_id", "title", "starts_at", "ends_at", "location", "owner_id", "kind"],
    Document: ["matter_id", "title", "kind", "created_by_id", "created_at"],
    DocumentVersion: ["document_id", "number", "original_name", "checksum", "uploaded_by_id", "created_at"],
    Opportunity: ["contact_id", "title", "stage", "amount", "owner_id", "next_action", "lost_reason", "created_at"],
    FinanceEntry: ["matter_id", "description", "kind", "amount", "due_date", "created_at"],
    Payment: ["entry_id", "amount", "date", "note", "created_by_id", "is_legacy_import", "reversal_of_id", "operation_key", "created_at"],
    ContractTemplate: ["name", "category", "description", "body", "is_active", "created_by_id", "created_at", "updated_at"],
    Contract: ["title", "template_id", "matter_id", "client_id", "document_id", "created_by_id", "created_at"],
    ContractRevision: ["contract_id", "document_version_id", "number", "title", "template_name", "source_body", "values", "rendered_text", "checksum", "created_by_id", "created_at", "operation_key"],
    Goal: ["title", "description", "metric", "target", "manual_value", "starts_on", "ends_on", "owner_id", "niche", "created_by_id", "archived", "created_at", "updated_at"],
    GoalUpdate: ["goal_id", "previous_value", "value", "note", "actor_id", "created_at"],
    AuditEvent: ["actor_id", "action", "object_type", "object_id", "description", "created_at"],
}


@organization_required
@require_GET
def export_workspace(request):
    """Export authorized records and original bytes without exposing storage paths."""
    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    finance_allowed = request.membership.role in {"owner", "manager"}
    manifest = {
        "schema_version": 2, "organization": {"id": request.organization.pk, "name": request.organization.name, "practice_areas": request.organization.practice_areas},
        "generated_at": timezone.now().isoformat(), "scope": "Somente registros autorizados ao usuário no momento da exportação.",
        "finance_included": finance_allowed, "counts": {}, "files": [],
        "notes": ["Valores monetários são strings decimais. Datas usam ISO 8601.", "Usuários referenciados têm somente identificador e nome de exibição; credenciais e dados de autenticação não são exportados.", "A auditoria contém apenas eventos de objetos ainda acessíveis.", "Modelos arquivados referenciados por contratos autorizados preservam os vínculos de reconstrução.", "Metas financeiras seguem as permissões de direção/gestão; a portabilidade permanece disponível após expiração do plano.", "Metas automáticas exportam a configuração; seu progresso pode ser recalculado pelos registros autorizados incluídos no pacote.", "Este pacote não inclui módulos ainda não implementados nem substitui o backup operacional."],
    }
    records = {}
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for model, fields in EXPORT_FIELDS.items():
                if model in {FinanceEntry, Payment} and not finance_allowed:
                    continue
                queryset = accessible_audit(request.user, request.organization, request.membership.role, for_export=True) if model is AuditEvent else scoped_queryset(request.user, request.organization, model, for_export=True)
                key = model._meta.model_name
                values = []
                for obj in queryset.iterator():
                    item = {"id": obj.pk, "organization_id": request.organization.pk}
                    for field in fields:
                        value = getattr(obj, field)
                        item[field] = value.isoformat() if hasattr(value, "isoformat") else str(value) if isinstance(value, (Decimal, UUID)) else value
                    if model is Matter:
                        item["member_ids"] = list(obj.members.values_list("pk", flat=True))
                    if model is DocumentVersion:
                        safe_name = Path(obj.original_name.replace("\\", "/")).name
                        archive_path = f"files/{obj.document_id}/{obj.pk}-{safe_name}"
                        digest = hashlib.sha256()
                        byte_count = 0
                        try:
                            with obj.file.open("rb") as source, archive.open(archive_path, "w") as target:
                                for chunk in source.chunks():
                                    target.write(chunk)
                                    digest.update(chunk)
                                    byte_count += len(chunk)
                        except (FileNotFoundError, OSError):
                            raise Http404("Um arquivo da exportação não está disponível. A administração deve verificar a integridade do armazenamento.") from None
                        if digest.hexdigest() != obj.checksum:
                            raise Http404("A integridade de um arquivo não pôde ser confirmada. A exportação foi interrompida.")
                        item["archive_path"] = archive_path
                        manifest["files"].append({"path": archive_path, "sha256": digest.hexdigest(), "bytes": byte_count})
                    values.append(item)
                records[key] = values
                manifest["counts"][key] = len(values)
            # Preserve the meaning of responsibility/history relations without
            # including account credentials, e-mails, or membership settings.
            user_ids = set()
            for rows in records.values():
                for row in rows:
                    for field in ("owner_id", "actor_id", "created_by_id", "uploaded_by_id", "confirmed_by_id"):
                        if row.get(field):
                            user_ids.add(row[field])
                    user_ids.update(row.get("member_ids", []))
            records["users"] = [
                {"id": user.pk, "display_name": user.get_full_name() or f"Usuário #{user.pk}"}
                for user in get_user_model().objects.filter(pk__in=user_ids).order_by("pk")
            ]
            manifest["counts"]["users"] = len(records["users"])
            payload = json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")
            archive.writestr("records.json", payload)
            manifest["files"].append({"path": "records.json", "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        output.seek(0)
        audit(organization=request.organization, actor=request.user, action="workspace.exported", description="Exportação dos registros e arquivos autorizados.")
        response = FileResponse(output, as_attachment=True, filename=f"jumbi-exportacao-{timezone.localdate().isoformat()}.zip", content_type="application/zip")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    except Exception:
        output.close()
        raise
