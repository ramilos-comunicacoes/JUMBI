"""Authenticated internal API. Unsupported external acts fail explicitly."""
import hashlib
import json
from functools import wraps
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse

from .access import require_integration_manager, visible_communications
from .credentials import encrypt_credentials
from .models import ApiRequest, IntegrationAccount, IntegrationProvider, MonitoringRule, SyncRun, IntegrationCapability
from .security import canonical_request_hash


def error(code, message, status=400):
    return JsonResponse({"code": code, "message": message}, status=status)


def endpoint(methods):
    def decorate(fn):
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                return error("METHOD_NOT_ALLOWED", "Método não permitido.", 405)
            if not request.user.is_authenticated:
                return error("UNAUTHORIZED", "Autenticação requerida.", 401)
            try:
                require_integration_manager(request.user, getattr(request, "organization", None))
                if request.method == "GET":
                    return fn(request, *args, **kwargs)
                if len(request.body) > 32768:
                    return error("PAYLOAD_TOO_LARGE", "Corpo da requisição excede 32 KB.", 413)
                body = json.loads(request.body.decode()) if request.body else {}
                if not isinstance(body, dict):
                    return error("INVALID_JSON", "Envie um objeto JSON.")
                request.command = body
                key = request.headers.get("Idempotency-Key", "")
                if not key or len(key) > 200:
                    return error("MISSING_IDEMPOTENCY_KEY", "Informe Idempotency-Key de até 200 caracteres.")
                digest = hashlib.sha256(f"{request.user.pk}:{request.method}:{request.path}:{key}".encode()).hexdigest()
                payload = canonical_request_hash(body)
                with transaction.atomic():
                    from apps.core.models import Organization
                    Organization.objects.select_for_update().get(pk=request.organization.pk)
                    # Recheck after waiting for the office lock: a platform
                    # administrator may have suspended access in the meantime.
                    require_integration_manager(request.user, request.organization)
                    command, _ = ApiRequest.objects.get_or_create(organization=request.organization, key_hash=digest, defaults={"payload_hash": payload})
                    command = ApiRequest.objects.select_for_update().get(pk=command.pk)
                    if command.payload_hash != payload:
                        return error("IDEMPOTENCY_CONFLICT", "A chave já foi usada com dados diferentes.", 409)
                    if command.status_code:
                        return JsonResponse(command.response, status=command.status_code)
                    response = fn(request, *args, **kwargs)
                    command.response = json.loads(response.content)
                    command.status_code = response.status_code
                    command.save(update_fields=["response", "status_code"])
                    return response
            except PermissionDenied:
                return error("FORBIDDEN", "Acesso reservado à direção e gestão autorizadas.", 403)
            except Http404:
                return error("NOT_FOUND", "Registro indisponível.", 404)
            except ValidationError as exc:
                return error("VALIDATION_ERROR", " ".join(exc.messages))
            except (ValueError, TypeError, UnicodeError):
                return error("INVALID_INPUT", "Confira os tipos, identificadores e datas enviados.")
        return wrapped
    return decorate


def account_json(account):
    return {"id": str(account.pk), "provider_code": account.provider.code, "label": account.label,
        "environment": account.environment, "status": account.status, "enabled": account.enabled,
        "external_principal_id": account.external_principal_id, "has_credentials": account.has_credentials}


@endpoint(["GET"])
def list_providers(request):
    return JsonResponse({"results": [{"code": p.code, "name": p.name, "authorization_status": p.authorization_status} for p in IntegrationProvider.objects.all()], "next_cursor": None})


@endpoint(["GET", "POST"])
def accounts_collection(request):
    if request.method == "GET":
        return JsonResponse({"results": [account_json(a) for a in IntegrationAccount.objects.filter(organization=request.organization).select_related("provider")], "next_cursor": None})
    body = request.command
    provider = get_object_or_404(IntegrationProvider, code=body.get("provider_code"))
    credentials = body.get("credentials", {})
    if not isinstance(credentials, dict):
        return error("VALIDATION_ERROR", "Credenciais devem ser um objeto.")
    account = IntegrationAccount(organization=request.organization, provider=provider, label=body.get("label", ""),
        environment=body.get("environment", "production"), external_principal_id=body.get("external_principal_id", ""),
        encrypted_credentials=encrypt_credentials(credentials), has_credentials=bool(credentials), status="NOT_HOMOLOGATED")
    account.full_clean()
    account.save()
    return JsonResponse(account_json(account), status=201)


@endpoint(["GET", "PATCH"])
def account_detail(request, account_id):
    account = get_object_or_404(IntegrationAccount, pk=account_id, organization=request.organization)
    if request.method == "PATCH":
        body = request.command
        if "label" in body:
            account.label = body["label"]
        if "enabled" in body:
            if not isinstance(body["enabled"], bool):
                return error("VALIDATION_ERROR", "enabled deve ser booleano.")
            account.enabled = body["enabled"]
        if "credentials" in body:
            if not isinstance(body["credentials"], dict):
                return error("VALIDATION_ERROR", "Credenciais devem ser um objeto.")
            account.encrypted_credentials = encrypt_credentials(body["credentials"])
            account.has_credentials = bool(body["credentials"])
        account.full_clean()
        account.save()
    return JsonResponse(account_json(account))


@endpoint(["POST"])
def validate_account(request, account_id):
    get_object_or_404(IntegrationAccount, pk=account_id, organization=request.organization)
    return error("NOT_HOMOLOGATED", "O cadastro de credenciais não comprova conexão. A homologação deste conector ainda não está disponível.", 501)


@endpoint(["GET", "POST"])
def monitors_collection(request):
    if request.method == "GET":
        return JsonResponse({"results": [{"id": str(r.pk), "label": r.label, "kind": r.kind, "enabled": r.enabled, "contract_status": r.contract_status} for r in MonitoringRule.objects.filter(organization=request.organization)], "next_cursor": None})
    body = request.command
    account = get_object_or_404(IntegrationAccount, pk=body.get("account_id"), organization=request.organization, enabled=True)
    rule = MonitoringRule(organization=request.organization, account=account, label=body.get("label", ""), kind=body.get("kind", ""), value=body.get("value", ""), oab_uf=body.get("oab_uf", ""))
    rule.full_clean()
    rule.save()
    return JsonResponse({"id": str(rule.pk), "label": rule.label, "kind": rule.kind, "enabled": rule.enabled, "contract_status": rule.contract_status}, status=201)


@endpoint(["POST"])
def start_monitor_run(request, monitor_id):
    from .djen_client import run_independent_searches
    rule = get_object_or_404(MonitoringRule, pk=monitor_id, organization=request.organization, enabled=True)
    if rule.account.provider.code != "djen" or rule.kind != MonitoringRule.Kind.LAWYER_NAME:
        return error("UNSUPPORTED_MONITOR", "A execução disponível pesquisa nome de advogado no DJEN. Outros conectores e critérios isolados aguardam homologação.", 501)
    result = run_independent_searches(organization=request.organization, target_name=rule.value, account=rule.account, operator=request.user, date_from=request.command.get("date_from"), date_to=request.command.get("date_to"))
    return JsonResponse({"id": str(result.id), "status": result.status, "status_url": reverse("integrations:api_get_run", args=[result.id])})


@endpoint(["GET"])
def get_run(request, run_id):
    run = get_object_or_404(SyncRun, pk=run_id, organization=request.organization)
    return JsonResponse({"id": str(run.pk), "status": run.status, "page_count": run.page_count, "item_count": run.item_count, "coverage_status": run.coverage_status, "errors": run.errors})


@endpoint(["GET"])
def list_coverage(request):
    return JsonResponse({"results": [{"tribunal": c.deployment.tribunal, "capability": c.capability, "documentation_status": c.documentation_status, "authorization_status": c.authorization_status, "health_status": c.health_status} for c in IntegrationCapability.objects.select_related("deployment")], "next_cursor": None})


@endpoint(["GET"])
def list_communications(request):
    from django.core.paginator import Paginator
    page = Paginator(visible_communications(request.user, request.organization).order_by("-created_at"), 50).get_page(request.GET.get("page"))
    return JsonResponse({"results": [{"id": str(c.pk), "external_id": c.external_id, "case_number": c.case_number, "tribunal": c.tribunal, "review_status": c.review_status, "deadline_status": c.deadline_status} for c in page], "next_cursor": str(page.next_page_number()) if page.has_next() else None})


@endpoint(["POST"])
def review_communication(request, communication_id):
    from apps.legal.services import visible_matters
    from .triage_services import confirm_communication, dismiss_communication
    body = request.command
    comm = get_object_or_404(visible_communications(request.user, request.organization), pk=communication_id)
    if body.get("decision") == "MATCH_CONFIRMED":
        matter = get_object_or_404(visible_matters(request.user, request.organization), pk=body.get("matter_id"))
        comm, review = confirm_communication(communication=comm, actor=request.user, matter=matter,
            due_date=date.fromisoformat(body.get("due_date", "")), notes=body.get("reason", ""))
    elif body.get("decision") == "NOT_RELEVANT":
        comm, review = dismiss_communication(communication=comm, actor=request.user, reason=body.get("reason", ""))
    else:
        return error("VALIDATION_ERROR", "Decisão desconhecida.")
    return JsonResponse({"id": review.pk, "communication_id": str(comm.pk), "decision": review.decision}, status=201)


@endpoint(["POST"])
def authorize_official_action(request, communication_id):
    get_object_or_404(visible_communications(request.user, request.organization), pk=communication_id)
    return error("OFFICIAL_ACTION_UNAVAILABLE", "Atos oficiais e ciência processual não estão homologados nesta versão.", 501)


@endpoint(["POST"])
def create_daily_report_api(request):
    from .word_report import generate_daily_docx_report
    report, _ = generate_daily_docx_report(request.organization, operator=request.user)
    return JsonResponse({"id": str(report.pk), "status": "COMPLETE", "status_url": reverse("integrations:download_report", args=[report.pk])}, status=201)
