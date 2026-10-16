"""Comunica PJe & DJEN daily research routine for Geórgia de Andrade Almeida.

Searches 3 distinct fields separately:
1. Communication content ('teor')
2. Party name ('parte')
3. Lawyer name ('advogado')

Deduplicates strictly by communication_id (never solely by case number,
because the same process can receive multiple notices on the same day).
Consolidates matches and feeds the deadline triage queue.
"""

from datetime import timedelta
from django.db import transaction
from django.utils import timezone

from .models import CourtCase, Deadline, DJENCommunication, DJENSearchRun, Matter


GEORGIA_NAME = "Geórgia de Andrade Almeida"


def extract_proposed_deadline(content_text, base_date):
    """Safely inspect text for deadline keywords without fabricating unverified dates."""
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

    if days is not None:
        return None, f"{days} dias mencionados; conferir termo inicial"
    return None, "A apurar na conferência"


@transaction.atomic
def run_daily_djen_search(*, organization, operator, base_date=None, records_source=None, sim_failures=None, queried_name=None):
    """Execute the daily search across the 3 fields and consolidate deduplicated results."""
    date = base_date or timezone.localdate()
    sim_failures = sim_failures or []

    from apps.integrations.djen_client import resolve_search_target, run_independent_searches
    from apps.integrations.models import CourtCommunication, SyncRun
    from apps.integrations.access import require_integration_manager, visible_communications
    require_integration_manager(operator, organization)
    resolved_name = resolve_search_target(organization, queried_name)
    if records_source is None:
        result = run_independent_searches(organization=organization, operator=operator, target_name=resolved_name, base_date=date)
        records_source = []
        for item in visible_communications(operator, organization).filter(hits__monitor__value=resolved_name).filter(available_date=date).distinct():
            criteria = set(item.hits.values_list("criteria_matched", flat=True))
            records_source.append({"communication_id": item.external_id, "court": item.tribunal or "DJEN",
                "court_unit": item.body_or_court, "case_number": item.case_number or "", "full_text": item.sanitized_text,
                "found_in_teor": "teor" in criteria, "found_in_parte": "parte" in criteria, "found_in_advogado": "advogado" in criteria})
        if result.status != SyncRun.Status.COMPLETE:
            sim_failures = [*sim_failures, "Coleta parcial ou indisponível. Confira as ocorrências e páginas pendentes na central de integrações."]

    run = DJENSearchRun.objects.create(
        organization=organization,
        base_date=date,
        queried_name=resolved_name,
        fields_searched=["teor", "parte", "advogado"],
        operator=operator,
        status=DJENSearchRun.Status.COMPLETE,
        courts_searched=sorted({item.get("court") for item in records_source if item.get("court")}) or ["DJEN"],
    )

    # Simulated/Injected feed of records (e.g. from Comunica PJe scraper, API or test payload)
    raw_feed = records_source

    # 1. Search in 'teor'
    # 2. Search in 'parte'
    # 3. Search in 'advogado'
    consolidated = {}
    total_found_raw = 0

    for item in raw_feed:
        # Determine matches in each of the 3 fields
        matches = []
        if item.get("found_in_teor", False):
            matches.append("teor")
        if item.get("found_in_parte", False):
            matches.append("parte")
        if item.get("found_in_advogado", False):
            matches.append("advogado")

        if not matches:
            # Check text directly if boolean flags not explicitly provided
            text = item.get("full_text", "")
            parties = item.get("parties", "")
            lawyer = item.get("lawyer_name", "")
            if resolved_name.lower() in text.lower():
                matches.append("teor")
            if resolved_name.lower() in parties.lower():
                matches.append("parte")
            if resolved_name.lower() in lawyer.lower():
                matches.append("advogado")

        if matches:
            total_found_raw += 1
            cid = item["communication_id"]
            if cid in consolidated:
                # Merge matched criteria
                for m in matches:
                    if m not in consolidated[cid]["matched_fields"]:
                        consolidated[cid]["matched_fields"].append(m)
            else:
                item["matched_fields"] = matches
                consolidated[cid] = item

    created_comms = []
    for cid, item in consolidated.items():
        # Check if case exists in office
        matter = None
        court_case = CourtCase.objects.filter(
            organization=organization,
            number=item.get("case_number", "")
        ).select_related("matter").first()
        if court_case:
            matter = court_case.matter

        prop_date, deadline_desc = extract_proposed_deadline(item.get("full_text", "") or item.get("summary", ""), date)

        comm = DJENCommunication.objects.create(
            organization=organization,
            search_run=run,
            communication_id=cid,
            court=item.get("court", "Tribunal"),
            court_unit=item.get("court_unit", "Vara"),
            case_number=item.get("case_number", ""),
            parties=item.get("parties", ""),
            content_summary=item.get("summary", "") or item.get("full_text", "")[:300],
            full_text=item.get("full_text", ""),
            matched_fields=item["matched_fields"],
            proposed_due_date=prop_date,
            deadline_text=deadline_desc,
            matter=matter,
            status=DJENCommunication.Status.PENDING_REVIEW,
        )
        created_comms.append(comm)

    run.total_found = total_found_raw
    run.total_deduplicated = len(created_comms)
    if sim_failures:
        run.status = DJENSearchRun.Status.PARTIAL
        run.errors = "; ".join(sim_failures)
    run.finished_at = timezone.now()
    run.save(update_fields=["total_found", "total_deduplicated", "status", "errors", "finished_at"])

    return run, created_comms


def get_default_djen_sample(date, lawyer_name=None):
    """Sample daily notifications for demonstration and routine testing."""
    lawyer = lawyer_name or GEORGIA_NAME
    return [
        {
            "communication_id": f"DJEN-{date.strftime('%Y%m%d')}-001",
            "court": "TRT13",
            "court_unit": "1ª Vara do Trabalho de João Pessoa",
            "case_number": "0000123-45.2026.5.13.0001",
            "parties": "José da Silva x Empresa Exemplo Ltda",
            "summary": "Intimação para apresentação de contrarrazões ao recurso ordinário no prazo de 8 dias.",
            "full_text": f"Fica intimado(a) o(a) advogado(a) {lawyer} para apresentar contrarrazões ao recurso ordinário no prazo de oito dias.",
            "lawyer_name": lawyer,
            "found_in_advogado": True,
            "found_in_teor": True,
        },
        {
            "communication_id": f"DJEN-{date.strftime('%Y%m%d')}-002",
            "court": "TRF1",
            "court_unit": "3ª Vara Federal Cível",
            "case_number": "1002345-67.2026.4.01.3400",
            "parties": "Maria Souza x INSS",
            "summary": "Ciência de laudo pericial médico favorável. Manifestação em 15 dias.",
            "full_text": f"Vista à parte autora, representada por {lawyer}, pelo prazo de 15 dias.",
            "lawyer_name": lawyer,
            "found_in_advogado": True,
        },
        {
            "communication_id": f"DJEN-{date.strftime('%Y%m%d')}-003",
            "court": "TJBA",
            "court_unit": "2ª Vara de Família",
            "case_number": "8009876-54.2026.8.05.0001",
            "parties": f"{lawyer} e Outros",
            "summary": "Despacho de mero expediente sem prazo fixado.",
            "full_text": f"Autos em cartório para vista às partes. Parte citada: {lawyer}.",
            "lawyer_name": lawyer,
            "found_in_parte": True,
            "found_in_teor": True,
        },
    ]
