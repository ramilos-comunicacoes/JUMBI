"""Web UI views for JUMBI Integrations Hub.

Provides dashboard, connectors center, monitoring rules, triage queue,
coverage directory, and Word report generator.
"""
from datetime import date, datetime
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.models import Membership
from apps.legal.models import CourtCase as Case, Matter
from .djen_client import (
    DJENClient,
    is_georgia_office,
    resolve_search_target,
    run_independent_searches,
    run_independent_georgia_searches,
)
from .models import (
    CourtCommunication,
    DailyReport,
    IntegrationAccount,
    IntegrationCapability,
    IntegrationProvider,
    MonitoringRule,
    SourceDeployment,
    SyncRun,
)
from .triage_services import confirm_communication, dismiss_communication, list_triage_queue
from .word_report import generate_daily_docx_report
from .access import require_integration_manager, visible_communications
from .credentials import encrypt_credentials
from apps.legal.services import visible_matters


def _require_manager(request):
    require_integration_manager(request.user, getattr(request, "organization", None))
    return True



@login_required
@require_http_methods(["GET", "POST"])
def connectors(request):
    """Central de Conectores e APIs judiciais."""
    if not _require_manager(request):
        return redirect("legal:dashboard")

    org = request.organization
    is_georgia = is_georgia_office(org)
    default_target = resolve_search_target(org)

    # Handle actions
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "add_connection":
                provider_code = request.POST.get("provider_code", "").strip()
                label = request.POST.get("label", "").strip()
                environment = request.POST.get("environment", "production")
                client_id = request.POST.get("client_id", "").strip()
                api_key = request.POST.get("api_key", "").strip()

                provider = IntegrationProvider.objects.filter(code=provider_code).first()
                if not provider:
                    raise ValidationError("Selecione um provedor cadastrado.")
                if environment not in {"sandbox", "production"} or len(label) > 150 or len(client_id) > 120 or len(api_key) > 4000:
                    raise ValidationError("Confira os campos da conexão.")

                account = IntegrationAccount.objects.create(
                    organization=org,
                    provider=provider,
                    label=label or provider.name,
                    environment=environment,
                    external_principal_id=client_id,
                    encrypted_credentials=encrypt_credentials({"api_key": api_key}) if api_key else "",
                    has_credentials=bool(api_key),
                    status="NOT_HOMOLOGATED",
                )
                messages.success(request, f"Conexão '{account.label}' configurada com sucesso!")
                return redirect("integrations:connectors")

            elif action == "test_connection":
                provider_code = request.POST.get("provider_code", "").strip().lower()
                account_id = request.POST.get("account_id")
                account = IntegrationAccount.objects.filter(pk=account_id, organization=org).first() if account_id else None

                if provider_code == "djen" or (account and account.provider.code == "djen") or not provider_code:
                    client = DJENClient()
                    tribunals = client.fetch_tribunals(timeout=8.0)
                    if tribunals:
                        messages.success(request, "O endpoint público do DJEN respondeu à consulta de tribunais. Isso não confirma cobertura completa de publicações.")
                    else:
                        messages.error(request, "Não foi possível comprovar a resposta do DJEN agora. Tente novamente mais tarde.")
                else:
                    messages.info(request, "Este conector aguarda homologação. Credenciais cadastradas não comprovam conexão nem habilitam atos oficiais.")

                return redirect("integrations:connectors")

            elif action == "quick_sync_djen":
                target_name = request.POST.get("target_name", "").strip()
                oab_number = request.POST.get("oab_number", "").strip()
                oab_uf = request.POST.get("oab_uf", "").strip()
                court_sigla = request.POST.get("court_sigla", "").strip()

                resolved = resolve_search_target(org, target_name)
                results = run_independent_searches(
                    organization=org,
                    target_name=resolved,
                    oab_number=oab_number or None,
                    oab_uf=oab_uf or None,
                    court_sigla=court_sigla or None,
                    operator=request.user,
                )
                _search_message(request, results)
                return redirect("integrations:triage")
        except (ValidationError, ValueError, TypeError):
            messages.error(request, "Não foi possível processar a operação. Confira o preenchimento e a disponibilidade do provedor.")
            return redirect("integrations:connectors")

    accounts = IntegrationAccount.objects.filter(organization=org).select_related("provider")
    providers = IntegrationProvider.objects.all().order_by("name")
    total_deployments = SourceDeployment.objects.count()
    active_monitors = MonitoringRule.objects.filter(organization=org, enabled=True).count()
    pending_triage = CourtCommunication.objects.filter(organization=org, review_status=CourtCommunication.ReviewStatus.PENDING_REVIEW).count()

    catalog_connectors = []
    for code, name in [("djen", "Diário de Justiça Eletrônico Nacional"), ("mni-tjba", "MNI · TJBA"), ("mni-tjrj", "MNI · TJRJ"), ("domicilio-judicial", "Domicílio Judicial"), ("pdpj-webhook", "PDPJ Webhook"), ("inss-prevjud", "INSS / PrevJud"), ("pje", "PJe"), ("esaj", "e-SAJ")]:
        catalog_connectors.append({"code": code, "name": name,
            "status": "CONSULTA MANUAL" if code == "djen" else "NÃO HOMOLOGADO",
            "description": "Pesquisa pública por nome, período e tribunal, com indicação de falhas e páginas pendentes." if code == "djen" else "Recurso em preparação. O cadastro não ativa consulta, monitoramento automático nem atos oficiais."})

    return render(request, "integrations/connectors.html", {
        "page_title": "Conectores e APIs Judiciais",
        "active_nav": "connectors",
        "accounts": accounts,
        "providers": providers,
        "catalog_connectors": catalog_connectors,
        "total_deployments": total_deployments,
        "active_monitors": active_monitors,
        "pending_triage": pending_triage,
        "is_georgia": is_georgia,
        "default_target": default_target,
    })


@login_required
@require_http_methods(["GET", "POST"])
def monitors(request):
    """Regras de monitoramento ativas (personalizável por escritório ou Geórgia)."""
    if not _require_manager(request):
        return redirect("legal:dashboard")

    org = request.organization
    is_georgia = is_georgia_office(org)
    default_target = resolve_search_target(org)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create_rule":
            label = request.POST.get("label", "").strip()
            kind = request.POST.get("kind", "lawyer_name")
            value = request.POST.get("value", "").strip()
            oab_uf = request.POST.get("oab_uf", "").strip()

            if not value or len(value) > 200 or len(label) > 150 or kind not in dict(MonitoringRule.Kind.choices):
                messages.error(request, "Informe o termo ou nome para monitorar.")
            else:
                # Ensure default DJEN account exists for rule
                provider = IntegrationProvider.objects.filter(code="djen").first()
                account = IntegrationAccount.objects.filter(organization=org, provider=provider).first() if provider else None
                if not account:
                    account = IntegrationAccount.objects.filter(organization=org).first()
                if not account and provider:
                    account = IntegrationAccount.objects.create(organization=org, provider=provider, label="DJEN Padrão", environment="production")
                if not account:
                    messages.error(request, "Cadastre uma conta DJEN antes de criar o critério.")
                    return redirect("integrations:monitors")

                rule = MonitoringRule.objects.create(
                    organization=org,
                    account=account,
                    label=label or value,
                    kind=kind,
                    value=value,
                    oab_uf=oab_uf,
                    enabled=True,
                )
                messages.success(request, f"Regra de monitoramento '{rule.label}' criada com sucesso!")
                return redirect("integrations:monitors")

        elif action in {"sync_now", "search_custom"}:
            custom_name = request.POST.get("target_name", "").strip() or request.POST.get("custom_name", "").strip()
            oab_number = request.POST.get("oab_number", "").strip() or None
            oab_uf = request.POST.get("oab_uf", "").strip() or None
            court_sigla = request.POST.get("court_sigla", "").strip() or None
            date_from = request.POST.get("date_from", "").strip() or None
            date_to = request.POST.get("date_to", "").strip() or None

            resolved = resolve_search_target(org, custom_name=custom_name or None)
            try:
                results = run_independent_searches(organization=org, target_name=resolved, oab_number=oab_number,
                    oab_uf=oab_uf, court_sigla=court_sigla, date_from=date_from, date_to=date_to, operator=request.user)
            except (ValidationError, ValueError, TypeError):
                messages.error(request, "Confira os critérios e o período da pesquisa (até 31 dias).")
                return redirect("integrations:monitors")
            _search_message(request, results)
            return redirect("integrations:triage")

    rules = MonitoringRule.objects.filter(organization=org).order_by("-enabled", "label")
    recent_runs = SyncRun.objects.filter(organization=org).order_by("-started_at")[:10]

    return render(request, "integrations/monitors.html", {
        "page_title": "Monitoramentos Judiciais",
        "active_nav": "connectors",
        "rules": rules,
        "recent_runs": recent_runs,
        "is_georgia": is_georgia,
        "default_target": default_target,
    })


@login_required
@require_http_methods(["GET", "POST"])
def triage(request):
    """Fila de triagem de publicações e intimações judiciais."""
    if not _require_manager(request):
        return redirect("legal:dashboard")

    org = request.organization

    if request.method == "POST":
        action = request.POST.get("action")
        comm_id = request.POST.get("communication_id")
        try:
            comm = get_object_or_404(visible_communications(request.user, org), pk=comm_id)

            if action == "confirm":
                matter_id = request.POST.get("matter_id")
                matter = visible_matters(request.user, org).filter(pk=matter_id).first() if matter_id else None
                due_date = date.fromisoformat(request.POST.get("due_date", ""))
                notes = request.POST.get("notes", "")

                confirm_communication(
                    communication=comm,
                    actor=request.user,
                    matter=matter,
                    create_deadline=True,
                    due_date=due_date,
                    notes=notes,
                )
                messages.success(request, f"Comunicação {comm.external_id} confirmada. Prazo e tarefa gerados com sucesso!")

            elif action == "dismiss":
                reason = request.POST.get("reason", "Publicação não relevante")
                dismiss_communication(communication=comm, actor=request.user, reason=reason)
                messages.success(request, f"Comunicação {comm.external_id} descartada.")
        except (ValidationError, ValueError, TypeError) as exc:
            text = " ".join(exc.messages) if isinstance(exc, ValidationError) else "Confira a pasta e a data de vencimento na fonte oficial."
            messages.error(request, text)

        return redirect("integrations:triage")

    status_filter = request.GET.get("status", "pending")
    search = request.GET.get("q", "")
    queue = list_triage_queue(org, status=status_filter if status_filter != "all" else None, search=search)

    queue = queue.filter(pk__in=visible_communications(request.user, org).values("pk"))
    page = Paginator(queue, 20).get_page(request.GET.get("page"))
    matters = visible_matters(request.user, org).order_by("title")[:100]

    return render(request, "integrations/triage.html", {
        "page_title": "Triagem de Publicações & Prazos",
        "active_nav": "connectors",
        "communications": page,
        "page_obj": page,
        "status_filter": status_filter,
        "search": search,
        "matters": matters,
    })


@login_required
@require_http_methods(["GET"])
def coverage(request):
    """Cobertura e matriz de capacidades dos 33 tribunais."""
    if not _require_manager(request):
        return redirect("legal:dashboard")

    search = request.GET.get("q", "").strip()
    deployments = SourceDeployment.objects.prefetch_related("capabilities").all()

    if search:
        deployments = deployments.filter(tribunal__icontains=search)

    return render(request, "integrations/coverage.html", {
        "page_title": "Catálogo de tribunais",
        "active_nav": "connectors",
        "deployments": deployments.order_by("tribunal"),
        "search": search,
        "total_courts": deployments.count(),
    })


@login_required
@require_http_methods(["GET", "POST"])
def reports(request):
    """Relatórios diários em Word (.docx)."""
    if not _require_manager(request):
        return redirect("legal:dashboard")

    org = request.organization

    if request.method == "POST":
        report, _ = generate_daily_docx_report(org, operator=request.user)
        messages.success(request, f"Relatório diário gerado com sucesso! Arquivo: {report.filename}")
        return redirect("integrations:reports")

    reports_list = DailyReport.objects.filter(organization=org, operator=request.user).order_by("-created_at")
    return render(request, "integrations/reports.html", {
        "page_title": "Relatórios Diários Word (.docx)",
        "active_nav": "connectors",
        "reports": reports_list,
    })


@login_required
def download_report(request, pk):
    """Download docx report file."""
    org = request.organization
    require_integration_manager(request.user, org)
    report = get_object_or_404(DailyReport, pk=pk, organization=org, operator=request.user)
    ids = report.summary_counts.get("communication_ids")
    if ids is None or visible_communications(request.user, org).filter(pk__in=ids).count() != len(ids):
        raise PermissionDenied("O escopo mudou ou o relatório é legado. Gere um novo relatório para seu acesso atual.")
    if not report.file_bytes:
        raise Http404("Arquivo do relatório não encontrado.")

    response = HttpResponse(bytes(report.file_bytes), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response["Content-Disposition"] = f'attachment; filename="{report.filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _search_message(request, results):
    if results.status == SyncRun.Status.COMPLETE:
        messages.success(request, f"Pesquisa concluída nos critérios consultados: {results.item_count} ocorrência(s). Confira a fila de triagem.")
    else:
        messages.warning(request, "Pesquisa parcial ou indisponível. Confira as falhas e páginas pendentes; não é possível afirmar ausência de publicações.")
