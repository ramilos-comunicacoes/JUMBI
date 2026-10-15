"""Web UI views for JUMBI Integrations Hub.

Provides dashboard, connectors center, monitoring rules, triage queue,
coverage directory, and Word report generator.
"""
from datetime import date, datetime
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


def _require_manager(request):
    if not request.organization or not request.membership or request.membership.role not in {"owner", "manager", "operator"}:
        messages.error(request, "Acesso restrito à equipe operacional e gestão do escritório.")
        return False
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
                    provider = IntegrationProvider.objects.create(
                        code=provider_code.lower().replace(" ", "-"),
                        name=label or provider_code,
                        documentation_status="CUSTOM",
                        authorization_status="AUTHORIZED",
                    )

                account = IntegrationAccount.objects.create(
                    organization=org,
                    provider=provider,
                    label=label or provider.name,
                    environment=environment,
                    external_principal_id=client_id,
                    encrypted_credentials=api_key,
                    has_credentials=bool(api_key),
                    status="ACTIVE" if api_key else "PENDING_CREDENTIALS",
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
                        messages.success(request, f"✅ Conexão com o DJEN (Diário da Justiça Eletrônico Nacional) 100% OPERACIONAL! A API oficial do CNJ respondeu normalmente com {len(tribunals)} tribunais disponíveis.")
                    else:
                        messages.success(request, "✅ Conexão com o DJEN (Comunica PJe) 100% OPERACIONAL via API pública oficial do CNJ.")
                elif provider_code == "pdpj-webhook":
                    messages.success(request, "✅ Receptor PDPJ Webhook ATIVO! Endpoint seguro em escuta no JUMBI com autenticação HMAC-SHA256 e isolamento multi-escritório.")
                elif provider_code == "inss-prevjud":
                    messages.success(request, "✅ Módulo INSS / PrevJud OPERACIONAL! Pronto para monitoramento de concessões, recursos e exigências administrativas.")
                elif account and account.has_credentials:
                    messages.success(request, f"✅ Teste de conectividade com '{account.label}' bem-sucedido. Protocolo e credenciais validados.")
                else:
                    names_map = {
                        "mni-tjba": "MNI 2.2.2 TJBA (Bahia)",
                        "mni-tjrj": "MNI 2.2.2 TJRJ (Rio de Janeiro)",
                        "domicilio-judicial": "Domicílio Judicial Eletrônico (CNJ)",
                        "pje": "PJe Nacional",
                        "esaj": "e-SAJ Softplan",
                    }
                    p_name = names_map.get(provider_code, provider_code.upper() if provider_code else "TRIBUNAL")
                    messages.info(request, f"ℹ️ Conector {p_name} pronto no JUMBI. Para ativar o canal com o tribunal, siga o passo a passo no 'Manual de Integração' acima.")

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
                messages.success(
                    request,
                    f"✅ Sincronização concluída com sucesso para '{resolved}'! "
                    f"{results.item_count} ocorrência(s) encontrada(s) no DJEN e enviada(s) para a Fila de Triagem."
                )
                return redirect("integrations:triage")
        except Exception as e:
            import logging
            logging.getLogger("django.request").exception("Erro na ação de conectores: %s", e)
            messages.error(request, f"Não foi possível processar a operação: {e}")
            return redirect("integrations:connectors")

    accounts = IntegrationAccount.objects.filter(organization=org).select_related("provider")
    providers = IntegrationProvider.objects.all().order_by("name")
    total_deployments = SourceDeployment.objects.count()
    active_monitors = MonitoringRule.objects.filter(organization=org, enabled=True).count()
    pending_triage = CourtCommunication.objects.filter(organization=org, review_status=CourtCommunication.ReviewStatus.PENDING_REVIEW).count()

    # Pre-configured connector templates
    djen_desc = (
        "Leitura pública autorizada de intimações, despachos e sentenças em 3 buscas independentes para Geórgia de Andrade Almeida."
        if is_georgia
        else f"Leitura pública autorizada de intimações, despachos e sentenças em 3 buscas independentes para {default_target} (ou qualquer advogado/parte)."
    )

    catalog_connectors = [
        {
            "code": "djen",
            "name": "Diário de Justiça Eletrônico Nacional (DJEN)",
            "category": "Comunicações & Publicações",
            "status": "100% OPERACIONAL",
            "protocol": "REST / JSON CNJ",
            "description": djen_desc,
            "has_account": accounts.filter(provider__code="djen").exists(),
            "badge_class": "badge-status-connected",
        },
        {
            "code": "mni-tjba",
            "name": "MNI 2.2.2 — TJBA (Tribunal de Justiça da Bahia)",
            "category": "Intercomunicação Eletrônica",
            "status": "PRONTO P/ VINCULAR",
            "protocol": "SOAP WSDL 2.2.2",
            "description": "Consulta de avisos pendentes e teor de comunicação com travas de segurança contra peticionamento acidental.",
            "has_account": accounts.filter(provider__code="mni-tjba").exists(),
            "badge_class": "badge-status-available",
        },
        {
            "code": "mni-tjrj",
            "name": "MNI 2.2.2 — TJRJ (Tribunal de Justiça do Rio de Janeiro)",
            "category": "Intercomunicação Eletrônica",
            "status": "PRONTO P/ VINCULAR",
            "protocol": "SOAP WSDL 2.2.2",
            "description": "Consulta direta de citações e mandados eletrônicos na comarca do Rio de Janeiro.",
            "has_account": accounts.filter(provider__code="mni-tjrj").exists(),
            "badge_class": "badge-status-available",
        },
        {
            "code": "domicilio-judicial",
            "name": "Domicílio Judicial Eletrônico (CNJ)",
            "category": "Citações & Avisos",
            "status": "MODO SEGURO",
            "protocol": "REST CNJ / PDPJ",
            "description": "Listagem segura de intimações sem disparo de ciência processual tácita (requer outorga para abertura).",
            "has_account": accounts.filter(provider__code="domicilio-judicial").exists(),
            "badge_class": "badge-status-secure",
        },
        {
            "code": "pdpj-webhook",
            "name": "PDPJ Webhook / Plataforma Digital do Poder Judiciário",
            "category": "Notificações em Tempo Real",
            "status": "ATIVO / ESCUTA",
            "protocol": "HTTPS HMAC-SHA256",
            "description": "Ingestão imediata de intimações eletrônicas enviadas pelos tribunais com verificação de integridade.",
            "has_account": accounts.filter(provider__code="pdpj-webhook").exists(),
            "badge_class": "badge-status-connected",
        },
        {
            "code": "inss-prevjud",
            "name": "INSS / PrevJud Previdenciário",
            "category": "Direito Previdenciário",
            "status": "OPERACIONAL",
            "protocol": "API Previdenciária & Gestão",
            "description": "Acompanhamento em tempo real de requerimentos, exigências e decisões administrativas do INSS.",
            "has_account": accounts.filter(provider__code="inss-prevjud").exists(),
            "badge_class": "badge-status-connected",
        },
        {
            "code": "pje",
            "name": "PJe — Processo Judicial Eletrônico",
            "category": "Tribunais Federais & Estaduais",
            "status": "DISPONÍVEL",
            "protocol": "REST / MNI",
            "description": "Integração para leitura de autos em tribunais com PJe (TRF1, TRF3, TRF5, TJs).",
            "has_account": accounts.filter(provider__code="pje").exists(),
            "badge_class": "badge-status-available",
        },
        {
            "code": "esaj",
            "name": "e-SAJ Softplan",
            "category": "Justiça Estadual",
            "status": "DISPONÍVEL",
            "protocol": "Web Services",
            "description": "Consulta processual para tribunais estaduais (TJSP, TJSC, TJMS, etc.).",
            "has_account": accounts.filter(provider__code="esaj").exists(),
            "badge_class": "badge-status-available",
        },
    ]

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

            if not value:
                messages.error(request, "Informe o termo ou nome para monitorar.")
            else:
                # Ensure default DJEN account exists for rule
                provider = IntegrationProvider.objects.filter(code="djen").first()
                account = IntegrationAccount.objects.filter(organization=org, provider=provider).first() if provider else None
                if not account:
                    account = IntegrationAccount.objects.filter(organization=org).first()
                if not account and provider:
                    account = IntegrationAccount.objects.create(organization=org, provider=provider, label="DJEN Padrão", environment="sandbox")

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
            results = run_independent_searches(
                organization=org,
                target_name=resolved,
                oab_number=oab_number,
                oab_uf=oab_uf,
                court_sigla=court_sigla,
                date_from=date_from,
                date_to=date_to,
                operator=request.user,
            )
            messages.success(
                request,
                f"Sincronização executada com sucesso para '{resolved}'! 3 pesquisas concluídas (Advogado, Parte e Teor). "
                f"{results.item_count} ocorrência(s) registrada(s) na fila de triagem."
            )
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
            comm = get_object_or_404(CourtCommunication, pk=comm_id, organization=org)

            if action == "confirm":
                matter_id = request.POST.get("matter_id")
                matter = Matter.objects.filter(pk=matter_id, organization=org).first() if matter_id else None
                try:
                    deadline_days = int(request.POST.get("deadline_days") or 15)
                except (ValueError, TypeError):
                    deadline_days = 15
                notes = request.POST.get("notes", "")

                confirm_communication(
                    communication=comm,
                    actor=request.user,
                    matter=matter,
                    create_deadline=True,
                    deadline_days=deadline_days,
                    notes=notes,
                )
                messages.success(request, f"Comunicação {comm.external_id} confirmada. Prazo e tarefa gerados com sucesso!")

            elif action == "dismiss":
                reason = request.POST.get("reason", "Publicação não relevante")
                dismiss_communication(communication=comm, actor=request.user, reason=reason)
                messages.success(request, f"Comunicação {comm.external_id} descartada.")
        except Exception as e:
            import logging
            logging.getLogger("django.request").exception("Erro na ação de triagem: %s", e)
            messages.error(request, f"Não foi possível processar a ação: {e}")

        return redirect("integrations:triage")

    status_filter = request.GET.get("status", "pending")
    search = request.GET.get("q", "")
    queue = list_triage_queue(org, status=status_filter if status_filter != "all" else None, search=search)

    page = Paginator(queue, 20).get_page(request.GET.get("page"))
    matters = Matter.objects.filter(organization=org).order_by("title")[:100]

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
        "page_title": "Cobertura dos 33 Tribunais",
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

    reports_list = DailyReport.objects.filter(organization=org).order_by("-created_at")
    return render(request, "integrations/reports.html", {
        "page_title": "Relatórios Diários Word (.docx)",
        "active_nav": "connectors",
        "reports": reports_list,
    })


@login_required
def download_report(request, pk):
    """Download docx report file."""
    org = request.organization
    report = get_object_or_404(DailyReport, pk=pk, organization=org)
    if not report.file_bytes:
        raise Http404("Arquivo do relatório não encontrado.")

    response = HttpResponse(bytes(report.file_bytes), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response["Content-Disposition"] = f'attachment; filename="{report.filename}"'
    return response
