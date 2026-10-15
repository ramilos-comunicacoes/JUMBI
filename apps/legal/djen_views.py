"""Views for daily Comunica PJe / DJEN research and Word report downloads."""

import io
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .djen_report import generate_djen_word_report
from .djen_services import run_daily_djen_search
from .models import DJENCommunication, DJENSearchRun
from .views import can_edit, organization_required, scoped_queryset
from apps.integrations.access import require_integration_manager
from apps.integrations.djen_client import resolve_search_target


@organization_required
@require_GET
def djen_dashboard(request):
    """Dashboard of daily Comunica PJe searches for Georgia de Andrade Almeida."""
    require_integration_manager(request.user, request.organization)
    runs = DJENSearchRun.objects.filter(organization=request.organization).order_by("-base_date", "-started_at")
    selected_run = runs.first()

    run_id = request.GET.get("run")
    if run_id:
        selected_run = get_object_or_404(DJENSearchRun, pk=run_id, organization=request.organization)

    comms = scoped_queryset(request.user, request.organization, DJENCommunication).filter(search_run=selected_run).select_related("matter") if selected_run else []

    org_slug = (getattr(request.organization, "slug", "") or "").lower()
    org_name = (getattr(request.organization, "name", "") or "").lower()
    is_georgia = "georgia" in org_slug or "geórgia" in org_name or "georgia" in org_name
    office_lawyer = resolve_search_target(request.organization)

    return render(request, "legal/djen_dashboard.html", {
        "title": "DJEN · Rotina de Pesquisa Diária",
        "page_title": "Comunica PJe & DJEN",
        "active_nav": "djen",
        "runs": runs[:10],
        "selected_run": selected_run,
        "comms": comms,
        "can_edit": can_edit(request),
        "is_georgia": is_georgia,
        "office_lawyer": office_lawyer,
    })


@organization_required
@require_POST
def djen_execute_search(request):
    """Trigger the daily Comunica PJe search across the 3 fields for today's execution date."""
    if not can_edit(request):
        raise PermissionDenied("Permissão negada.")

    require_integration_manager(request.user, request.organization)
    queried_name = resolve_search_target(request.organization, request.POST.get("lawyer_name", ""))
    if not 3 <= len(queried_name) <= 200:
        messages.error(request, "Informe o nome completo, de 3 a 200 caracteres.")
        return redirect("legal:djen_dashboard")

    run, comms = run_daily_djen_search(
        organization=request.organization,
        operator=request.user,
        base_date=timezone.localdate(),
        queried_name=queried_name,
    )
    if run.status == "complete":
        messages.success(request, f"Pesquisa concluída nos critérios consultados: {run.total_deduplicated} comunicação/ões.")
    else:
        messages.warning(request, "Pesquisa parcial ou indisponível. Confira as falhas; o resultado não confirma ausência de publicações.")
    return redirect(f"{reverse('legal:djen_dashboard')}?run={run.pk}")


@organization_required
@require_GET
def djen_download_word_report(request, pk):
    """Download the Word (.docx) daily report with urgency colors and full header."""
    require_integration_manager(request.user, request.organization)
    run = get_object_or_404(DJENSearchRun, pk=pk, organization=request.organization)
    docx_bytes = generate_djen_word_report(run, list(scoped_queryset(request.user, request.organization, DJENCommunication).filter(search_run=run)))

    stream = io.BytesIO(docx_bytes)
    filename = f"relatorio-djen-{run.base_date.isoformat()}.docx"
    response = FileResponse(stream, as_attachment=True, filename=filename, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response["Cache-Control"] = "private, no-store"
    return response
