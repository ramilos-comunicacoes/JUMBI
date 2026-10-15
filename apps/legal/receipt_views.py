"""Views for downloading and printing personalized payment receipts."""

import io
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from .models import PaymentReceipt
from .receipt_services import generate_receipt_docx
from .views import can_manage_finance, organization_required, scoped_queryset


@organization_required
@require_GET
def download_receipt_docx(request, pk):
    """Download the receipt as a Word document (.docx)."""
    if not can_manage_finance(request):
        raise PermissionDenied("Acesso restrito ao financeiro e direção.")

    receipt = get_object_or_404(
        scoped_queryset(request.user, request.organization, PaymentReceipt).select_related("organization", "payment", "issued_by", "confirmed_by"),
        pk=pk,
        organization=request.organization,
    )
    docx_bytes = generate_receipt_docx(receipt)
    stream = io.BytesIO(docx_bytes)
    filename = f"recibo-{receipt.receipt_number}.docx"
    response = FileResponse(
        stream,
        as_attachment=True,
        filename=filename,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Cache-Control"] = "private, no-store"
    return response


@organization_required
@require_GET
def receipt_printable(request, pk):
    """Printable web view for the receipt with office branding."""
    if not can_manage_finance(request):
        raise PermissionDenied("Acesso restrito ao financeiro e direção.")

    receipt = get_object_or_404(
        scoped_queryset(request.user, request.organization, PaymentReceipt).select_related("organization", "payment", "issued_by", "confirmed_by"),
        pk=pk,
        organization=request.organization,
    )
    return render(request, "legal/receipt_printable.html", {
        "title": f"Recibo #{receipt.receipt_number}",
        "receipt": receipt,
        "org": request.organization,
    })
