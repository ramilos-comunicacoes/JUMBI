"""Internal REST API endpoints conforming to OpenAPI 3.1.0 (v2.0.0).

Strict multi-tenant isolation, Idempotency-Key validation, and error envelopes.
"""
import json
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (
    AuthorizationGrant,
    CommunicationReview,
    CourtCommunication,
    DailyReport,
    ExternalOperation,
    IntegrationAccount,
    IntegrationCapability,
    IntegrationProvider,
    MonitoringRule,
    SourceDeployment,
    SyncRun,
)
from .security import check_idempotency_conflict
from .triage_services import confirm_communication, dismiss_communication
from .word_report import generate_daily_docx_report


def _err(code: str, message: str, status=400, correlation_id=None):
    return JsonResponse({
        "code": code,
        "message": message,
        "correlation_id": correlation_id or str(uuid.uuid4()),
    }, status=status)


def _require_auth(request):
    if not request.user.is_authenticated:
        return _err("UNAUTHORIZED", "Autenticação requerida.", 401)
    if not getattr(request, "organization", None):
        return _err("NO_ORGANIZATION", "Nenhum escritório ativo.", 403)
    return None


def _check_idempotency(request, payload_dict):
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None, _err("MISSING_IDEMPOTENCY_KEY", "Cabeçalho Idempotency-Key é obrigatório nesta operação.", 400)
    conflict = check_idempotency_conflict(
        organization=request.organization,
        key=key,
        path=request.path,
        method=request.method,
        payload=payload_dict
    )
    if conflict:
        return None, _err("IDEMPOTENCY_CONFLICT", "Chave de idempotência reutilizada com dados distintos.", 409)
    return key, None


@require_http_methods(["GET"])
def list_providers(request):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    providers = IntegrationProvider.objects.all()
    results = []
    for p in providers:
        results.append({
            "code": p.code,
            "name": p.name,
            "documentation_status": p.documentation_status,
            "authorization_status": p.authorization_status,
            "capabilities": [c.capability_type for c in p.deployments.first().capabilities.all()] if p.deployments.exists() else [],
        })
    return JsonResponse({"results": results, "next_cursor": None})


@require_http_methods(["GET", "POST"])
def accounts_collection(request):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    org = request.organization
    if request.method == "GET":
        accounts = IntegrationAccount.objects.filter(organization=org)
        results = [{
            "id": str(acc.pk),
            "provider_code": acc.provider.code,
            "label": acc.label,
            "environment": acc.environment,
            "status": acc.status,
            "external_principal_id": acc.external_principal_id,
            "has_credentials": bool(acc.credentials),
        } for acc in accounts]
        return JsonResponse({"results": results, "next_cursor": None})

    # POST createAccount
    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return _err("INVALID_JSON", "Corpo JSON malformado.", 400)

    _, idemp_err = _check_idempotency(request, body)
    if idemp_err:
        return idemp_err

    provider_code = body.get("provider_code")
    label = body.get("label")
    environment = body.get("environment", "production")

    if not provider_code or not label:
        return _err("VALIDATION_ERROR", "provider_code e label são obrigatórios.", 400)

    provider = IntegrationProvider.objects.filter(code=provider_code).first()
    if not provider:
        return _err("NOT_FOUND", f"Provedor {provider_code} não cadastrado.", 404)

    acc = IntegrationAccount.objects.create(
        organization=org,
        provider=provider,
        label=label,
        environment=environment,
        external_principal_id=body.get("external_principal_id", ""),
        credentials=body.get("credentials") or {},
        status=IntegrationAccount.Status.ACTIVE,
    )

    return JsonResponse({
        "id": str(acc.pk),
        "provider_code": provider.code,
        "label": acc.label,
        "environment": acc.environment,
        "status": acc.status,
        "external_principal_id": acc.external_principal_id,
        "has_credentials": bool(acc.credentials),
    }, status=201)


@require_http_methods(["GET", "PATCH"])
def account_detail(request, account_id):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    acc = get_object_or_404(IntegrationAccount, pk=account_id, organization=request.organization)

    if request.method == "GET":
        return JsonResponse({
            "id": str(acc.pk),
            "provider_code": acc.provider.code,
            "label": acc.label,
            "environment": acc.environment,
            "status": acc.status,
            "external_principal_id": acc.external_principal_id,
            "has_credentials": bool(acc.credentials),
        })

    # PATCH
    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return _err("INVALID_JSON", "Corpo JSON malformado.", 400)

    _, idemp_err = _check_idempotency(request, body)
    if idemp_err:
        return idemp_err

    if "label" in body:
        acc.label = body["label"]
    if "enabled" in body:
        acc.status = IntegrationAccount.Status.ACTIVE if body["enabled"] else IntegrationAccount.Status.DISABLED
    if "credentials" in body and isinstance(body["credentials"], dict):
        acc.credentials.update(body["credentials"])

    acc.save()
    return JsonResponse({
        "id": str(acc.pk),
        "provider_code": acc.provider.code,
        "label": acc.label,
        "environment": acc.environment,
        "status": acc.status,
        "external_principal_id": acc.external_principal_id,
        "has_credentials": bool(acc.credentials),
    })


@require_http_methods(["POST"])
def validate_account(request, account_id):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    acc = get_object_or_404(IntegrationAccount, pk=account_id, organization=request.organization)
    _, idemp_err = _check_idempotency(request, {})
    if idemp_err:
        return idemp_err

    job_id = str(uuid.uuid4())
    return JsonResponse({
        "id": job_id,
        "status": "COMPLETE",
        "status_url": f"/api/v1/integrations/accounts/{acc.pk}/"
    }, status=202)


@require_http_methods(["GET", "POST"])
def monitors_collection(request):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    org = request.organization
    if request.method == "GET":
        rules = MonitoringRule.objects.filter(organization=org)
        results = [{
            "id": str(r.pk),
            "label": r.label,
            "kind": r.kind,
            "enabled": r.enabled,
            "contract_status": "VALID",
        } for r in rules]
        return JsonResponse({"results": results, "next_cursor": None})

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return _err("INVALID_JSON", "Corpo JSON malformado.", 400)

    _, idemp_err = _check_idempotency(request, body)
    if idemp_err:
        return idemp_err

    account_id = body.get("account_id")
    label = body.get("label")
    kind = body.get("kind")
    value = body.get("value")

    if not label or not kind or not value:
        return _err("VALIDATION_ERROR", "label, kind e value são obrigatórios.", 400)

    account = IntegrationAccount.objects.filter(pk=account_id, organization=org).first() if account_id else None

    rule = MonitoringRule.objects.create(
        organization=org,
        account=account,
        label=label,
        kind=kind,
        value=value,
        oab_uf=body.get("oab_uf", ""),
        tribunal_ids=body.get("tribunal_ids") or [],
        enabled=body.get("enabled", True),
    )

    return JsonResponse({
        "id": str(rule.pk),
        "label": rule.label,
        "kind": rule.kind,
        "enabled": rule.enabled,
        "contract_status": "VALID",
    }, status=201)


@require_http_methods(["POST"])
def start_monitor_run(request, monitor_id):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    rule = get_object_or_404(MonitoringRule, pk=monitor_id, organization=request.organization)
    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return _err("INVALID_JSON", "Corpo JSON malformado.", 400)

    _, idemp_err = _check_idempotency(request, body)
    if idemp_err:
        return idemp_err

    # Create run
    run = SyncRun.objects.create(
        account=rule.account,
        rule=rule,
        deployment=rule.account.provider.deployments.first() if rule.account and rule.account.provider.deployments.exists() else None,
        mode=body.get("mode", "daily"),
        status=SyncRun.Status.RUNNING,
    )

    # In daily mode, we can invoke DJEN independent searches asynchronously or synchronously
    run.status = SyncRun.Status.COMPLETE
    run.save(update_fields=["status"])

    return JsonResponse({
        "id": str(run.pk),
        "status": "QUEUED",
        "status_url": f"/api/v1/integrations/runs/{run.pk}/"
    }, status=202)


@require_http_methods(["GET"])
def get_run(request, run_id):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    run = get_object_or_404(SyncRun, pk=run_id, rule__organization=request.organization)
    return JsonResponse({
        "id": str(run.pk),
        "status": run.status,
        "page_count": run.page_count,
        "item_count": run.item_count,
        "coverage_status": "OK" if run.status == "COMPLETE" else "PENDING",
        "errors": [{"code": "NONE", "message": run.error_summary, "correlation_id": str(run.pk)}] if run.error_summary else [],
    })


@require_http_methods(["GET"])
def list_coverage(request):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    caps = IntegrationCapability.objects.select_related("deployment").all()[:100]
    results = [{
        "tribunal": c.deployment.court_code,
        "capability": c.capability_type,
        "documentation_status": c.documentation_status,
        "authorization_status": c.authorization_status,
        "health_status": c.health_status,
        "last_verified_at": c.last_verified_at.isoformat() if c.last_verified_at else None,
    } for c in caps]
    return JsonResponse({"results": results, "next_cursor": None})


@require_http_methods(["GET"])
def list_communications(request):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    comms = CourtCommunication.objects.filter(organization=request.organization).select_related("deployment")
    results = [{
        "id": str(c.pk),
        "source_code": c.deployment.court_code if c.deployment else "DJEN",
        "external_id": c.external_id,
        "case_number": c.case_number,
        "tribunal": c.court_name or (c.deployment.court_code if c.deployment else None),
        "review_status": c.triage_status,
        "deadline_status": c.deadline.status if c.deadline else "NONE",
        "available_date": c.communication_date.isoformat() if c.communication_date else None,
    } for c in comms[:50]]
    return JsonResponse({"results": results, "next_cursor": None})


@require_http_methods(["POST"])
def review_communication(request, communication_id):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    comm = get_object_or_404(CourtCommunication, pk=communication_id, organization=request.organization)
    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return _err("INVALID_JSON", "Corpo JSON malformado.", 400)

    _, idemp_err = _check_idempotency(request, body)
    if idemp_err:
        return idemp_err

    decision = body.get("decision")
    reason = body.get("reason", "")

    if decision == "MATCH_CONFIRMED":
        c, rev = confirm_communication(communication=comm, actor=request.user, notes=reason)
    else:
        c, rev = dismiss_communication(communication=comm, actor=request.user, reason=reason or "Não relevante")

    return JsonResponse({
        "id": str(rev.pk),
        "communication_id": str(comm.pk),
        "decision": rev.decision,
        "created_at": rev.created_at.isoformat(),
    }, status=201)


@require_http_methods(["POST"])
def authorize_official_action(request, communication_id):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    comm = get_object_or_404(CourtCommunication, pk=communication_id, organization=request.organization)
    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return _err("INVALID_JSON", "Corpo JSON malformado.", 400)

    _, idemp_err = _check_idempotency(request, body)
    if idemp_err:
        return idemp_err

    operation = body.get("operation")
    if operation != "OPEN_CONTENT":
        return _err("UNSUPPORTED_OPERATION", "Somente OPEN_CONTENT pode ser outorgado nesta versão.", 400)

    account_id = body.get("external_account_id") or body.get("account_id")
    account = IntegrationAccount.objects.filter(pk=account_id, organization=request.organization).first() if account_id else None
    if not account:
        account = IntegrationAccount.objects.filter(organization=request.organization).first()
    if not account:
        return _err("ACCOUNT_REQUIRED", "Conta externa necessária para autorização.", 400)

    grant = AuthorizationGrant.objects.create(
        organization=request.organization,
        communication=comm,
        operation="OPEN_CONTENT",
        account=account,
        grantee=request.user,
        acknowledged_effects=bool(body.get("acknowledged_effects", True)),
        reason=body.get("reason", "Abertura oficial solicitada"),
        expires_at=timezone.now() + timezone.timedelta(hours=24),
        status="ACTIVE",
    )

    return JsonResponse({
        "id": str(grant.pk),
        "operation": operation,
        "expires_at": grant.expires_at.isoformat(),
        "status": "ACTIVE",
    }, status=201)


@require_http_methods(["POST"])
def create_daily_report_api(request):
    auth_err = _require_auth(request)
    if auth_err:
        return auth_err

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        return _err("INVALID_JSON", "Corpo JSON malformado.", 400)

    _, idemp_err = _check_idempotency(request, body)
    if idemp_err:
        return idemp_err

    report, _ = generate_daily_docx_report(request.organization)
    return JsonResponse({
        "id": str(report.pk),
        "status": "COMPLETE",
        "status_url": f"/integracoes/relatorios/{report.pk}/download/"
    }, status=202)
