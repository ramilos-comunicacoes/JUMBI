"""DJEN (Diário de Justiça Eletrônico Nacional) public read-only client and search engine.

Features:
- Conservative rate limiting and pagination budget (1 concurrent request per host, min 2s interval)
- 3 independent searches for the name configured by the office:
  1. Communication content ('texto' / 'teor')
  2. Party name ('nomeParte')
  3. Lawyer name ('nomeAdvogado')
- Strict deduplication: matching all 3 criteria generates a single CourtCommunication with 3 MonitoringHits
- Preserves raw payloads in SourceRecord with SHA-256 integrity
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from django.db import transaction
from django.utils import timezone

from .models import (
    CourtCommunication,
    IntegrationAccount,
    IntegrationProvider,
    MonitoringHit,
    MonitoringRule,
    SourceDeployment,
    SourceRecord,
    SyncPage,
    SyncRun,
)
from .security import APPROVED_HOSTS, validate_allowed_url

logger = logging.getLogger(__name__)

GEORGIA_NAME = "Geórgia de Andrade Almeida"
DJEN_PRODUCTION_BASE = "https://comunicaapi.pje.jus.br/api/v1"
DJEN_SANDBOX_BASE = "https://hcomunicaapi.cnj.jus.br/api/v1"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirecionamento bloqueado", headers, fp)


class DJENClient:
    """Safe, rate-limited public read-only client for DJEN."""

    def __init__(self, base_url: str = DJEN_PRODUCTION_BASE, min_interval_seconds: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.min_interval_seconds = min_interval_seconds
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self._last_request_time = time.time()

    def fetch_tribunals(self, timeout: float = 20.0) -> list[dict]:
        """Fetch list of tribunals from DJEN."""
        url = f"{self.base_url}/comunicacao/tribunal"
        validate_allowed_url(url, APPROVED_HOSTS)
        self._rate_limit()

        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Jumbi-DJEN-Client/2.0",
            },
        )
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as resp:
                data = resp.read(2 * 1024 * 1024)
                return json.loads(data)
        except Exception as exc:
            logger.warning("DJEN fetch_tribunals falhou: %s", exc)
            return []

    def search_communications(self, query_params: Mapping[str, Any], timeout: float = 25.0) -> dict:
        """Execute a single filtered search on GET /comunicacao."""
        qs = urlencode({k: v for k, v in query_params.items() if v is not None})
        url = f"{self.base_url}/comunicacao?{qs}"
        validate_allowed_url(url, APPROVED_HOSTS)
        self._rate_limit()

        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Jumbi-DJEN-Client/2.0",
            },
        )
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as resp:
                raw = resp.read(4 * 1024 * 1024)
                return {
                    "success": True,
                    "status_code": resp.status,
                    "data": json.loads(raw),
                    "raw_bytes": raw,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
        except urllib.error.HTTPError as exc:
            retry_after = exc.headers.get("Retry-After")
            return {
                "success": False,
                "status_code": exc.code,
                "error": f"HTTP {exc.code}",
                "retry_after": retry_after,
            }
        except Exception as exc:
            return {
                "success": False,
                "status_code": 0,
                "error": str(exc),
            }


def sanitize_communication_text(raw_text: str) -> str:
    """Sanitize content to prevent HTML/XSS injection in previews."""
    if not raw_text:
        return ""
    # Strip dangerous HTML tags
    clean = re_replace_html(raw_text)
    return clean.strip()


def re_replace_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text)


def extract_proposed_deadline(content_text: str, base_date: date) -> tuple[date | None, str]:
    """Safely infer deadline mention without fabricating confirmed legal terms."""
    text_lower = (content_text or "").lower()
    days = None
    if "prazo de 15 dias" in text_lower or "quinze dias" in text_lower:
        days = 15
    elif "prazo de 5 dias" in text_lower or "cinco dias" in text_lower:
        days = 5
    elif "prazo de 10 dias" in text_lower or "dez dias" in text_lower:
        days = 10
    elif "prazo de 8 dias" in text_lower or "oito dias" in text_lower:
        days = 8
    elif "prazo de 20 dias" in text_lower or "vinte dias" in text_lower:
        days = 20
    elif "prazo de 30 dias" in text_lower or "trinta dias" in text_lower:
        days = 30

    if days is not None:
        return None, f"{days} dias mencionados; conferir termo inicial"
    return None, "A conferir"


class GeorgiaSearchResults(list):
    """Encapsulates the 3 independent criteria search outcomes and the associated SyncRun."""
    def __init__(self, criteria_results, sync_run):
        super().__init__(criteria_results)
        self.sync_run = sync_run
        self.status = sync_run.status
        self.item_count = sync_run.item_count
        self.page_count = sync_run.page_count
        self.id = sync_run.id


def is_georgia_office(organization) -> bool:
    """Check if the given organization belongs to Dra. Geórgia de Andrade Almeida."""
    if not organization:
        return False
    slug = getattr(organization, "slug", "").lower()
    name = getattr(organization, "name", "").lower()
    return "georgia" in slug or "georgia" in name or "geórgia" in name


def resolve_search_target(organization, custom_name: str | None = None) -> str:
    """Resolve the lawyer name to query.
    
    If custom_name is provided, uses it.
    If organization is Dra. Geórgia's office, defaults to 'Geórgia de Andrade Almeida'.
    Otherwise, checks the organization's active monitoring rules, then the office owner's name.
    """
    if custom_name and custom_name.strip():
        return custom_name.strip()
    from apps.core.preferences import office_preferences
    configured = office_preferences(organization)["djen_name"]
    if configured:
        return configured

    # Look for an active monitoring rule
    rule = MonitoringRule.objects.filter(
        organization=organization,
        enabled=True,
        kind=MonitoringRule.Kind.LAWYER_NAME,
    ).first()
    if rule and rule.value and rule.value.strip():
        return rule.value.strip()

    # Fallback to organization owner user full name
    try:
        owner_membership = organization.memberships.filter(role="owner", is_active=True).select_related("user").first()
        if owner_membership and owner_membership.user:
            full_name = owner_membership.user.get_full_name() or owner_membership.user.email
            if full_name and len(full_name.strip()) > 3:
                return full_name.strip()
    except Exception:
        pass

    fallback_title = getattr(organization, "system_title", None) or getattr(organization, "name", "")
    return fallback_title if fallback_title else "Advogado Titular"


@transaction.atomic
def run_independent_searches(
    *,
    organization,
    target_name: str | None = None,
    oab_number: str | None = None,
    oab_uf: str | None = None,
    court_sigla: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    account: IntegrationAccount | None = None,
    base_date: date | None = None,
    operator=None,
    mock_feed: list[dict] | None = None,
    sample_hits: list[dict] | None = None,
    client: DJENClient | None = None,
) -> GeorgiaSearchResults:
    """Execute the 3 independent searches (Advogado, Parte, Teor) for any lawyer or party.
    
    - In Dra. Geórgia's office: defaults to Geórgia de Andrade Almeida.
    - In any other office: fully customizable by lawyer name, OAB/UF, party, or tribunal.
    - Consolidates matches strictly by external_id, creating MonitoringHit records
      for all matched criteria with zero duplicate records.
    """
    from django.core.exceptions import ValidationError
    from .access import require_integration_manager
    if operator:
        require_integration_manager(operator, organization)
    search_name = resolve_search_target(organization, target_name)
    if not 3 <= len(search_name) <= 200:
        raise ValidationError("Informe um nome entre 3 e 200 caracteres.")
    def parsed_date(value):
        try:
            return date.fromisoformat(value) if isinstance(value, str) else value
        except ValueError as exc:
            raise ValidationError("Informe uma data válida no formato AAAA-MM-DD.") from exc
    date_from, date_to = parsed_date(date_from), parsed_date(date_to)
    if date_from and date_to and (date_to < date_from or (date_to - date_from).days > 31):
        raise ValidationError("Selecione um período de até 31 dias, com término após o início.")
    if account and (account.organization_id != organization.pk or not account.enabled or account.revoked_at):
        raise ValidationError("Conta externa indisponível para este escritório.")
    search_date = base_date or date_from or timezone.localdate()
    date_from_str = (date_from or search_date).isoformat()
    date_to_str = (date_to or search_date).isoformat()
    mock_feed = mock_feed if mock_feed is not None else sample_hits

    if account is None:
        provider = IntegrationProvider.objects.filter(code="djen").first()
        if not provider:
            provider = IntegrationProvider.objects.create(code="djen", name="DJEN", documentation_status="DOC", authorization_status="AUTH")
        account, _ = IntegrationAccount.objects.get_or_create(
            organization=organization,
            provider=provider,
            defaults={
                "label": f"DJEN — {search_name}",
                "environment": "production",
                "status": "ACTIVE_READ_ONLY",
            }
        )

    # Ensure monitor rules exist for this search
    rules = {}
    for kind, crit_title in [
        (MonitoringRule.Kind.LAWYER_NAME, "Advogado"),
        (MonitoringRule.Kind.PARTY_NAME, "Parte"),
        (MonitoringRule.Kind.CONTENT_TEXT, "Teor"),
    ]:
        rule, _ = MonitoringRule.objects.get_or_create(
            organization=organization,
            account=account,
            kind=kind,
            value=search_name,
            defaults={
                "label": f"DJEN {crit_title}: {search_name}",
                "oab_uf": oab_uf or "",
                "contract_status": "ACTIVE_READ_ONLY",
                "enabled": True,
            },
        )
        rules[kind] = rule

    # Create SyncRun
    sync_run = SyncRun.objects.create(
        organization=organization,
        account=account,
        monitor=rules[MonitoringRule.Kind.LAWYER_NAME],
        date_from=date_from or search_date,
        date_to=date_to or search_date,
        mode="daily",
        status=SyncRun.Status.RUNNING,
        operator=operator,
        coverage_status="BUSCAS_INDEPENDENTES_EM_ANDAMENTO",
    )

    client = client or DJENClient(
        base_url=DJEN_PRODUCTION_BASE if account.environment == "production" else DJEN_SANDBOX_BASE
    )

    consolidated_items: dict[str, dict] = {}
    errors = []
    total_raw_found = 0
    criteria_stats = {}

    # Build 3 distinct criteria queries
    adv_params: dict[str, Any] = {
        "nomeAdvogado": search_name,
        "dataDisponibilizacaoInicio": date_from_str,
        "dataDisponibilizacaoFim": date_to_str,
    }
    if oab_number:
        adv_params["numeroOab"] = oab_number
    if oab_uf:
        adv_params["ufOab"] = oab_uf.upper()
    if court_sigla:
        adv_params["siglaTribunal"] = court_sigla.upper()

    parte_params: dict[str, Any] = {
        "nomeParte": search_name,
        "dataDisponibilizacaoInicio": date_from_str,
        "dataDisponibilizacaoFim": date_to_str,
    }
    if court_sigla:
        parte_params["siglaTribunal"] = court_sigla.upper()

    teor_params: dict[str, Any] = {
        "texto": search_name,
        "dataDisponibilizacaoInicio": date_from_str,
        "dataDisponibilizacaoFim": date_to_str,
    }
    if court_sigla:
        teor_params["siglaTribunal"] = court_sigla.upper()

    search_criteria = [
        ("advogado", MonitoringRule.Kind.LAWYER_NAME, adv_params),
        ("parte", MonitoringRule.Kind.PARTY_NAME, parte_params),
        ("teor", MonitoringRule.Kind.CONTENT_TEXT, teor_params),
    ]

    for criterion_name, kind, params in search_criteria:
        page_index = 1
        has_more = True
        criteria_items = []

        while has_more and page_index <= 2:
            if mock_feed is not None:
                matching_in_feed = []
                for item in mock_feed:
                    matched = False
                    lawyer_val = (item.get("lawyer_name") or item.get("recipient") or "").lower()
                    party_val = (item.get("parties") or item.get("recipient") or "").lower()
                    content_val = (item.get("full_text") or item.get("content") or item.get("texto") or "").lower()

                    target_lower = search_name.lower()
                    if criterion_name == "advogado" and (target_lower in lawyer_val or target_lower in content_val):
                        matched = True
                    elif criterion_name == "parte" and (target_lower in party_val or target_lower in content_val):
                        matched = True
                    elif criterion_name == "teor" and (target_lower in content_val or target_lower in lawyer_val):
                        matched = True
                    if matched:
                        matching_in_feed.append(item)

                resp_data = {"items": matching_in_feed, "total": len(matching_in_feed)}
                raw_bytes = json.dumps(resp_data).encode("utf-8")
                page_hash = hashlib.sha256(raw_bytes).hexdigest()
                has_more = False
            else:
                # Actual DJEN live API call
                fetch_params = dict(params, pagina=page_index, itensPorPagina=20)
                call_res = client.search_communications(fetch_params, timeout=5.0)
                if not call_res.get("success"):
                    errors.append({
                        "code": f"DJEN_FETCH_ERROR_{criterion_name.upper()}",
                        "message": call_res.get("error", "Falha de comunicação"),
                        "correlation_id": f"{sync_run.id}-{criterion_name}-{page_index}",
                    })
                    break

                resp_data = call_res.get("data", {})
                if not isinstance(resp_data, dict) or not any(key in resp_data for key in ("items", "comunicacoes")):
                    errors.append({"code": "INVALID_RESPONSE", "message": "A API não retornou a estrutura de resultados esperada."})
                    break
                raw_bytes = call_res.get("raw_bytes", b"{}")
                page_hash = call_res.get("sha256", "")
                items = resp_data.get("items", []) or resp_data.get("comunicacoes", [])
                if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                    errors.append({"code": "INVALID_RESPONSE", "message": "A API retornou registros em formato inválido."})
                    break
                if not items or len(items) < 20:
                    has_more = False

            items = resp_data.get("items", []) or resp_data.get("comunicacoes", [])
            items_count = len(items)
            criteria_items.extend(items)

            SyncPage.objects.create(
                organization=organization,
                run=sync_run,
                court_code="DJEN",
                cursor_or_page=f"{criterion_name}-p{page_index}",
                items_count=items_count,
                payload_hash=page_hash,
            )
            page_index += 1

        if has_more and page_index > 2:
            errors.append({"code": "PAGE_BUDGET", "message": "Há páginas pendentes. Restrinja o período ou tribunal e execute novamente."})
        total_raw_found += len(criteria_items)
        criteria_stats[criterion_name] = len(criteria_items)

        for raw_item in criteria_items:
            ext_id = str(raw_item.get("id") or raw_item.get("communication_id") or raw_item.get("hash") or raw_item.get("numeroComunicacao") or raw_item.get("external_id"))
            if not ext_id or ext_id == "None":
                ext_id = hashlib.sha256(f"{raw_item.get('numeroProcesso')}-{raw_item.get('texto', '')[:100]}".encode()).hexdigest()[:32]

            if ext_id in consolidated_items:
                if criterion_name not in consolidated_items[ext_id]["matched_criteria"]:
                    consolidated_items[ext_id]["matched_criteria"].append(criterion_name)
            else:
                consolidated_items[ext_id] = {
                    "raw": raw_item,
                    "matched_criteria": [criterion_name],
                    "monitor_rule": rules[kind],
                }

    # Persist consolidated CourtCommunication and MonitoringHits
    created_count = 0
    for ext_id, item_data in consolidated_items.items():
        raw = item_data["raw"]
        matched_criteria = item_data["matched_criteria"]

        full_text = raw.get("texto") or raw.get("full_text") or raw.get("conteudo") or raw.get("content") or ""
        sanitized = sanitize_communication_text(full_text)
        case_num = (
            raw.get("numeroprocessocommascara")
            or raw.get("numero_processo")
            or raw.get("numeroProcesso")
            or raw.get("case_number")
        )
        tribunal_sigla = raw.get("siglaTribunal") or raw.get("court") or "DJEN"
        body_name = raw.get("nomeOrgao") or raw.get("court_body") or ""
        comm_type = raw.get("tipoComunicacao") or raw.get("tipoDocumento") or raw.get("tipo") or "Intimação"

        # Extract recipient
        recipient = ""
        if raw.get("destinatarioadvogados") and isinstance(raw["destinatarioadvogados"], list):
            names = [a.get("advogado", {}).get("nome") for a in raw["destinatarioadvogados"] if a.get("advogado", {}).get("nome")]
            if names:
                recipient = ", ".join(names)
        if not recipient and raw.get("destinatarios") and isinstance(raw["destinatarios"], list):
            names = [d.get("nome") for d in raw["destinatarios"] if d.get("nome")]
            if names:
                recipient = ", ".join(names)
        if not recipient:
            recipient = raw.get("destinatario") or raw.get("recipient") or raw.get("lawyer_name") or search_name

        # Extract dates
        avail_date = search_date
        raw_date = raw.get("data_disponibilizacao")
        if raw_date and isinstance(raw_date, str) and len(raw_date) >= 10:
            try:
                avail_date = date.fromisoformat(raw_date[:10])
            except ValueError:
                pass

        prop_due, deadline_label = extract_proposed_deadline(sanitized, avail_date)

        # Store SourceRecord
        raw_hash = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
        source_rec, _ = SourceRecord.objects.get_or_create(
            organization=organization,
            source_code="djen",
            external_id=ext_id,
            defaults={
                "payload_hash": raw_hash,
                "raw_payload": raw,
            },
        )

        comm, created = CourtCommunication.objects.get_or_create(
            organization=organization,
            source_code="djen",
            external_id=str(ext_id)[:150],
            defaults={
                "case_number": str(case_num or "")[:80],
                "tribunal": str(tribunal_sigla or "")[:40],
                "body_or_court": str(body_name or "")[:200],
                "communication_type": str(comm_type or "")[:80],
                "content_text": full_text,
                "sanitized_text": sanitized,
                "available_date": avail_date,
                "publication_date": avail_date,
                "recipient_name": str(recipient or "")[:200],
                "review_status": CourtCommunication.ReviewStatus.PENDING_REVIEW,
                "deadline_status": str(deadline_label or "A CONFERIR")[:40],
                "proposed_due_date": prop_due,
                "sync_run": sync_run,
                "raw_record": source_rec,
            },
        )
        if created:
            created_count += 1

        # Create MonitoringHits for all matched criteria
        for crit in matched_criteria:
            hit_rule = rules.get(
                MonitoringRule.Kind.LAWYER_NAME if crit == "advogado"
                else MonitoringRule.Kind.PARTY_NAME if crit == "parte"
                else MonitoringRule.Kind.CONTENT_TEXT
            )
            MonitoringHit.objects.get_or_create(
                organization=organization,
                communication=comm,
                monitor=hit_rule,
                criteria_matched=crit,
                defaults={
                    "hit_detail": f"Localizado em busca de {crit} para {search_name}",
                },
            )

    # Complete SyncRun
    sync_run.page_count = SyncPage.objects.filter(run=sync_run).count()
    sync_run.item_count = len(consolidated_items)
    sync_run.errors = errors
    sync_run.finished_at = timezone.now()
    if errors:
        sync_run.status = SyncRun.Status.PARTIAL if sync_run.page_count else SyncRun.Status.FAILED
        sync_run.coverage_status = "PARCIAL_COM_OCORRENCIAS"
    else:
        sync_run.status = SyncRun.Status.COMPLETE
        sync_run.coverage_status = f"3_BUSCAS_CONCLUIDAS_{search_name.upper().replace(' ', '_')[:30]}"
    sync_run.save(update_fields=["page_count", "item_count", "errors", "status", "coverage_status", "finished_at"])

    criteria_results = [
        {"criterion": "advogado", "items_found": criteria_stats.get("advogado", 0)},
        {"criterion": "parte", "items_found": criteria_stats.get("parte", 0)},
        {"criterion": "teor", "items_found": criteria_stats.get("teor", 0)},
    ]

    return GeorgiaSearchResults(criteria_results, sync_run)


def run_independent_georgia_searches(
    *,
    organization,
    account: IntegrationAccount | None = None,
    base_date: date | None = None,
    operator=None,
    mock_feed: list[dict] | None = None,
    sample_hits: list[dict] | None = None,
    client: DJENClient | None = None,
) -> GeorgiaSearchResults:
    """Backward-compatible wrapper for Dra. Geórgia de Andrade Almeida searches."""
    return run_independent_searches(
        organization=organization,
        target_name=GEORGIA_NAME,
        account=account,
        base_date=base_date,
        operator=operator,
        mock_feed=mock_feed,
        sample_hits=sample_hits,
        client=client,
    )
