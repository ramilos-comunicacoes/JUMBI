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
from .views import can_edit, organization_required


@organization_required
@require_GET
def djen_dashboard(request):
    """Dashboard of daily Comunica PJe searches for Georgia de Andrade Almeida."""
    runs = DJENSearchRun.objects.filter(organization=request.organization).order_by("-base_date", "-started_at")
    selected_run = runs.first()

    run_id = request.GET.get("run")
    if run_id:
        selected_run = get_object_or_404(DJENSearchRun, pk=run_id, organization=request.organization)

    comms = DJENCommunication.objects.filter(search_run=selected_run).select_related("matter") if selected_run else []

    return render(request, "legal/djen_dashboard.html", {
        "title": "DJEN · Rotina de Pesquisa Diária",
        "page_title": "Comunica PJe & DJEN",
        "active_nav": "djen",
        "runs": runs[:10],
        "selected_run": selected_run,
        "comms": comms,
        "can_edit": can_edit(request),
    })


@organization_required
@require_POST
def djen_execute_search(request):
    """Trigger the daily Comunica PJe search across the 3 fields for today's execution date."""
    if not can_edit(request):
        raise PermissionDenied("Permissão negada.")

    run, comms = run_daily_djen_search(
        organization=request.organization,
        operator=request.user,
        base_date=timezone.localdate(),
    )
    messages.success(request, f"Pesquisa diária concluída para {run.queried_name}. {run.total_deduplicated} comunicação/ões identificada(s).")
    return redirect(reverse("legal:djen_dashboard"))


@organization_required
@require_GET
def djen_download_word_report(request, pk):
    """Download the Word (.docx) daily report with urgency colors and full header."""
    run = get_object_or_404(DJENSearchRun, pk=pk, organization=request.organization)
    docx_bytes = generate_djen_word_report(run)

    stream = io.BytesIO(docx_bytes)
    filename = f"relatorio-djen-{run.base_date.isoformat()}.docx"
    response = FileResponse(stream, as_attachment=True, filename=filename, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response["Cache-Control"] = "private, no-store"
    return response
