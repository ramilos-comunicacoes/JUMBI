"""Pure-Python OOXML (.docx) daily report generator.

Generates professional Word reports of judicial syncs and communications
without any external C or binary dependencies (pure Python zipfile + XML).
Respects America/Fortaleza timezone and office identity.
"""
import hashlib
import html
import io
import zipfile
import zoneinfo
from datetime import datetime
from django.core.files.base import ContentFile
from django.db.models import Q
from django.utils import timezone

from .models import CourtCommunication, DailyReport, SyncRun


FORTALEZA_TZ = zoneinfo.ZoneInfo("America/Fortaleza")


def _xml_escape(text):
    if not text:
        return ""
    return html.escape(str(text)).replace("\r\n", "\n").replace("\r", "\n")


def _p(text, bold=False, italic=False, size_pt=11, color="222222", align="left", space_after=120):
    escaped = _xml_escape(text)
    r_props = []
    if bold:
        r_props.append("<w:b/>")
    if italic:
        r_props.append("<w:i/>")
    if size_pt:
        r_props.append(f'<w:sz w:val="{int(size_pt * 2)}"/>')
    if color:
        r_props.append(f'<w:color w:val="{color}"/>')

    p_props = []
    if align != "left":
        p_props.append(f'<w:jc w:val="{align}"/>')
    if space_after:
        p_props.append(f'<w:spacing w:after="{space_after}"/>')

    p_pr = f"<w:pPr>{''.join(p_props)}</w:pPr>" if p_props else ""
    r_pr = f"<w:rPr>{''.join(r_props)}</w:rPr>" if r_props else ""

    # Split lines
    lines = escaped.split("\n")
    runs = []
    for idx, line in enumerate(lines):
        runs.append(f"<w:r>{r_pr}<w:t xml:space=\"preserve\">{line}</w:t></w:r>")
        if idx < len(lines) - 1:
            runs.append("<w:r><w:br/></w:r>")

    return f"<w:p>{p_pr}{''.join(runs)}</w:p>"


def _table_row(cells, is_header=False, bg_color=None):
    tc_xml = []
    for text, width in cells:
        tc_pr = [f'<w:tcW w:w="{width}" w:type="dxa"/>']
        if is_header or bg_color:
            fill = "0F4050" if is_header else (bg_color or "F4F4F6")
            tc_pr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>')
        tc_pr.append('<w:tcMar><w:top w:w="120" w:type="dxa"/><w:bottom w:w="120" w:type="dxa"/><w:left w:w="140" w:type="dxa"/><w:right w:w="140" w:type="dxa"/></w:tcMar>')

        color = "FFFFFF" if is_header else "222222"
        p = _p(text, bold=is_header, size_pt=9.5 if not is_header else 10, color=color, space_after=40)
        tc_xml.append(f"<w:tc><w:tcPr>{''.join(tc_pr)}</w:tcPr>{p}</w:tc>")

    tr_pr = "<w:trPr><w:tblHeader/></w:trPr>" if is_header else ""
    return f"<w:tr>{tr_pr}{''.join(tc_xml)}</w:tr>"


def generate_daily_docx_report(organization, base_date=None, sync_run=None, operator=None):
    """Generate OOXML .docx report for daily communications and save DailyReport record."""
    if not base_date:
        base_date = timezone.localdate()

    now_fortaleza = datetime.now(FORTALEZA_TZ)
    office_name = getattr(organization, "system_title", None) or organization.name

    # Query communications for base_date or sync_run
    comms_qs = CourtCommunication.objects.filter(
        organization=organization
    ).select_related("matter", "court_case")

    if sync_run:
        comms_qs = comms_qs.filter(sync_run=sync_run)
    else:
        comms_qs = comms_qs.filter(Q(available_date=base_date) | Q(publication_date=base_date))

    if operator:
        from .access import require_integration_manager, visible_communications
        require_integration_manager(operator, organization)
        comms_qs = comms_qs.filter(pk__in=visible_communications(operator, organization).values("pk"))
    comms = list(comms_qs.order_by("tribunal", "case_number"))

    total_comms = len(comms)
    pending_count = sum(1 for c in comms if c.review_status == CourtCommunication.ReviewStatus.PENDING_REVIEW)
    confirmed_count = sum(1 for c in comms if c.review_status == CourtCommunication.ReviewStatus.MATCH_CONFIRMED)
    dismissed_count = sum(1 for c in comms if c.review_status == CourtCommunication.ReviewStatus.NOT_RELEVANT)

    # Search criteria stats
    search_breakdown = {}
    court_breakdown = {}
    for c in comms:
        c_name = c.court_name
        court_breakdown[c_name] = court_breakdown.get(c_name, 0) + 1

    # Document body XML
    body_elements = []

    # Title & Header
    body_elements.append(_p(office_name.upper(), bold=True, size_pt=18, color="F5A000", space_after=80))
    body_elements.append(_p("RELATÓRIO DIÁRIO DE COMUNICAÇÕES JUDICIAIS · DJEN & PDPJ", bold=True, size_pt=14, color="0F4050", space_after=140))
    body_elements.append(_p(f"Data de Referência: {base_date.strftime('%d/%m/%Y')} | Emitido em: {now_fortaleza.strftime('%d/%m/%Y às %H:%M:%S')} (Horário de Fortaleza)", italic=True, size_pt=9.5, color="71717A", space_after=240))

    # Divider
    body_elements.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="12" w:space="8" w:color="E4E4E7"/></w:pBdr></w:pPr></w:p>')

    # Executive Summary Section
    body_elements.append(_p("1. RESUMO EXECUTIVO", bold=True, size_pt=12, color="0F4050", space_after=120))

    summary_text = (
        f"Neste período de coleta, foram localizadas {total_comms} publicação(ões) e comunicações oficiais.\n"
        f"• Pendentes de triagem: {pending_count}\n"
        f"• Confirmadas com prazo/tarefa gerados: {confirmed_count}\n"
        f"• Descartadas/Sem providência necessária: {dismissed_count}"
    )
    body_elements.append(_p(summary_text, size_pt=10.5, space_after=200))

    # Court Distribution Table
    if court_breakdown:
        body_elements.append(_p("2. DISTRIBUIÇÃO POR TRIBUNAL", bold=True, size_pt=12, color="0F4050", space_after=100))
        tbl_rows = [_table_row([("Tribunal / Órgão", 5000), ("Quantidade de Publicações", 3500)], is_header=True)]
        for court_k, count_v in sorted(court_breakdown.items()):
            tbl_rows.append(_table_row([(court_k, 5000), (str(count_v), 3500)]))

        tbl_xml = f'<w:tbl><w:tblPr><w:tblW w:w="8500" w:type="dxa"/><w:tblBorders><w:top w:val="single" w:sz="4" w:color="D4D4D8"/><w:bottom w:val="single" w:sz="4" w:color="D4D4D8"/><w:insideH w:val="single" w:sz="4" w:color="E4E4E7"/></w:tblBorders></w:tblPr>{"".join(tbl_rows)}</w:tbl>'
        body_elements.append(tbl_xml)
        body_elements.append(_p("", space_after=200))

    # Detailed Communications Table
    body_elements.append(_p("3. COMUNICAÇÕES COLETADAS EM DETALHES", bold=True, size_pt=12, color="0F4050", space_after=120))

    if comms:
        for idx, c in enumerate(comms, start=1):
            c_name = c.court_name or (c.deployment.court_code if c.deployment else "Órgão Oficial")
            status_desc = dict(CourtCommunication.TriageStatus.choices).get(c.triage_status, c.triage_status)
            date_str = c.communication_date.strftime("%d/%m/%Y") if c.communication_date else "—"

            body_elements.append(_p(f"Item #{idx:02d} · Processo: {c.case_number or 'Sem número'} | {c_name}", bold=True, size_pt=10.5, color="0F4050", space_after=40))
            from .djen_client import is_georgia_office
            fallback_name = "Geórgia de Andrade Almeida" if is_georgia_office(organization) else office_name
            dest_name = c.recipient_name or fallback_name
            item_details = (
                f"Data da Disponibilização: {date_str} | Tipo: {c.communication_type or 'Publicação'}\n"
                f"Destinatário / Pesquisado: {dest_name}\n"
                f"Situação na Triagem: {status_desc}"
            )
            body_elements.append(_p(item_details, italic=True, size_pt=9.5, color="52525B", space_after=60))

            if c.full_content:
                snippet = c.full_content[:600] + ("..." if len(c.full_content) > 600 else "")
                body_elements.append(_p(f"Trecho do Conteúdo:\n\"{snippet}\"", size_pt=9, color="3F3F46", space_after=140))
    else:
        body_elements.append(_p("Nenhuma comunicação encontrada para os critérios selecionados nesta data.", italic=True, size_pt=10, color="71717A", space_after=180))

    # Errors, Blockers and Disclosures Section
    body_elements.append(_p("4. REGISTRO DE EXECUÇÃO E DECLARAÇÕES", bold=True, size_pt=12, color="0F4050", space_after=100))
    disclosures = (
        "• Monitoramento executado em conformidade com as regras de leitura pública permitida do DJEN.\n"
        "• Nenhuma ciência tácita ou intimação pessoal foi registrada de forma automática.\n"
        "• A conferência dos prazos processuais cabe ao advogado responsável habilitado nos autos."
    )
    body_elements.append(_p(disclosures, size_pt=9, color="71717A", space_after=200))

    # Assemble Document XML
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    {''.join(body_elements)}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>"""

    # Package as OOXML .docx zip archive
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        # [Content_Types].xml
        z.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""")

        # _rels/.rels
        z.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""")

        # word/document.xml
        z.writestr("word/document.xml", doc_xml.encode("utf-8"))

    buffer.seek(0)
    docx_bytes = buffer.getvalue()

    file_hash = hashlib.sha256(docx_bytes).hexdigest()
    report = DailyReport.objects.create(
        organization=organization,
        base_date=base_date,
        operator=operator,
        format="docx",
        summary_counts={
            "office": office_name,
            "communication_ids": [str(c.pk) for c in comms],
            "total": total_comms,
            "pending": pending_count,
            "confirmed": confirmed_count,
            "dismissed": dismissed_count,
            "courts": court_breakdown,
            "generated_at": now_fortaleza.isoformat(),
        },
        file_bytes=docx_bytes,
        file_hash=file_hash,
    )

    return report, docx_bytes

