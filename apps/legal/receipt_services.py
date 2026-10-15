"""Receipt generation and verification services with custom office branding and OOXML DOCX."""

import io
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Payment, PaymentReceipt


def generate_receipt_number(organization):
    """Generate a unique sequential receipt number within the organization."""
    year = timezone.localdate().year
    prefix = f"REC-{year}-"
    last = PaymentReceipt.objects.filter(
        organization=organization,
        receipt_number__startswith=prefix,
    ).order_by("-receipt_number").first()

    if last:
        try:
            seq = int(last.receipt_number.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


@transaction.atomic
def issue_payment_receipt(*, payment, actor, payer_name=None, payer_document=None, payment_method="PIX / Transferência", notes=""):
    """Issue an immutable receipt for a confirmed payment."""
    from .services import _authorize_write
    from apps.core.models import Organization
    _authorize_write(actor=actor, obj=payment)
    Organization.objects.select_for_update().get(pk=payment.organization_id)
    if payment.reversal_of_id or Payment.objects.filter(reversal_of=payment).exists():
        raise ValidationError("Não é permitido emitir recibo para estornos.")

    entry = payment.entry
    matter = entry.matter if entry else None
    org = payment.organization

    payer_name = (payer_name or (entry.matter.client.name if entry and entry.matter and entry.matter.client else "Cliente")).strip()
    payer_document = (payer_document or (entry.matter.client.document if entry and entry.matter and entry.matter.client else "")).strip()

    receipt_number = generate_receipt_number(org)
    remaining = entry.balance if entry else Decimal("0.00")

    receipt = PaymentReceipt.objects.create(
        organization=org,
        receipt_number=receipt_number,
        payment=payment,
        matter=matter,
        payer_name=payer_name,
        payer_document=payer_document,
        amount=payment.amount,
        payment_date=payment.date or timezone.localdate(),
        payment_method=payment_method,
        reference_description=entry.description if entry else "Serviços jurídicos",
        remaining_balance=remaining,
        issued_by=actor,
        confirmed_by=payment.created_by or actor,
    )
    return receipt


def generate_receipt_docx(receipt):
    """Generate a clean OOXML Word document for the personalized receipt."""
    org = receipt.organization
    date_str = receipt.payment_date.strftime("%d/%m/%Y")
    issue_date_str = receipt.created_at.strftime("%d/%m/%Y às %H:%M")

    lines = [
        f"RECIBO DE PAGAMENTO #{receipt.receipt_number}",
        f"VALOR: R$ {receipt.amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", "."),
        "",
        f"Recebemos de: {receipt.payer_name}" + (f" (CPF/CNPJ: {receipt.payer_document})" if receipt.payer_document else ""),
        f"A importância de: R$ {receipt.amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", "."),
        f"Forma de pagamento: {receipt.payment_method}",
        f"Data do pagamento: {date_str}",
        "",
        f"Referente a: {receipt.reference_description}",
        f"Saldo remanescente do lançamento: R$ {receipt.remaining_balance:,.2f}".replace(",", "_").replace(".", ",").replace("_", "."),
        "",
        f"Recebedor: {org.name}",
        f"Documento do escritório: {org.document or '—'}",
        f"Emitido por: {receipt.issued_by.get_full_name() or receipt.issued_by.email} em {issue_date_str}",
        f"Baixa conferida por: {receipt.confirmed_by.get_full_name() or receipt.confirmed_by.email if receipt.confirmed_by else '—'}",
    ]

    def paragraph(text, title=False):
        style = '<w:pPr><w:pStyle w:val="Title"/><w:jc w:val="center"/></w:pPr>' if title else ""
        runs = '<w:br/>'.join('<w:t xml:space="preserve">' + escape(line) + '</w:t>' for line in text.split("\n"))
        return f"<w:p>{style}<w:r>{runs}</w:r></w:p>"

    body_xml = (
        paragraph(f"{org.name}\nRECIBO #{receipt.receipt_number}", title=True)
        + "".join(paragraph(part) for part in lines)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
    )

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body_xml}</w:body></w:document>'
    )

    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": doc_xml,
    }

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 14, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content.encode("utf-8"))
    return output.getvalue()
