"""Daily Word (.docx) report generator for DJEN & Comunica PJe research results.

Generates standard OOXML docx with office identity header, urgency color badges,
summary counts, grouping by court, and highlighted 'A conferir' sections.
"""

import io
import zipfile
from xml.sax.saxutils import escape
from django.utils import timezone


def generate_djen_word_report(search_run, communications=None):
    """Generate a formatted Word (.docx) report for the daily research run."""
    org = search_run.organization
    comms = communications if communications is not None else search_run.communications.all()

    today_str = search_run.base_date.strftime("%d/%m/%Y")
    now_str = timezone.localtime(search_run.finished_at or timezone.now()).strftime("%d/%m/%Y às %H:%M (UTC-3)")
    status_label = "PESQUISA COMPLETA" if search_run.status == "complete" else "PESQUISA PARCIAL (COM FALHAS OU PENDÊNCIAS)"
    operator_name = search_run.operator.get_full_name() or search_run.operator.email

    # Count stats
    total = len(comms)
    urgent_count = sum(1 for c in comms if c.proposed_due_date and (c.proposed_due_date - search_run.base_date).days <= 2)
    attention_count = sum(1 for c in comms if c.proposed_due_date and 3 <= (c.proposed_due_date - search_run.base_date).days <= 5)
    horizon_count = sum(1 for c in comms if c.proposed_due_date and (c.proposed_due_date - search_run.base_date).days > 5)
    pending_count = sum(1 for c in comms if not c.proposed_due_date or c.status == "pending_review")

    # Group by court
    courts_map = {}
    for c in comms:
        courts_map.setdefault(c.court, []).append(c)

    # XML Helper
    def p(text, style="", color=None, bold=False):
        style_xml = f'<w:pStyle w:val="{style}"/>' if style else ""
        p_pr = f'<w:pPr>{style_xml}</w:pPr>'
        bold_xml = '<w:b/>' if bold else ""
        color_xml = f'<w:color w:val="{color}"/>' if color else ""
        r_pr = f'<w:rPr>{bold_xml}{color_xml}</w:rPr>'
        runs = '<w:br/>'.join('<w:t xml:space="preserve">' + escape(line) + '</w:t>' for line in text.split("\n"))
        return f"<w:p>{p_pr}<w:r>{r_pr}{runs}</w:r></w:p>"


    def callout_box(title, text, hex_color="E2E8F0", text_color="0F172A"):
        return (
            '<w:p><w:pPr><w:pBdr>'
            f'<w:left w:val="single" w:sz="36" w:space="12" w:color="{text_color}"/>'
            '</w:pBdr>'
            f'<w:shd w:val="clear" w:color="auto" w:fill="{hex_color}"/>'
            '</w:pPr>'
            f'<w:r><w:rPr><w:b/><w:color w:val="{text_color}"/></w:rPr><w:t xml:space="preserve">{escape(title)}</w:t></w:r>'
            f'<w:r><w:br/><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
            '</w:p>'
        )

    body = []

    # Document Header
    body.append(p(f"{org.name.upper()}", style="Title", bold=True, color="0B1320"))
    body.append(p("RELATÓRIO DIÁRIO DE COMUNICAÇÕES PROCESSUAIS — COMUNICA PJe / DJEN", bold=True, color="B45309"))
    body.append(p(f"Nome pesquisado: {search_run.queried_name}"))
    body.append(p(f"Data-base da pesquisa: {today_str} (campo: disponibilização)"))
    body.append(p(f"Gerado em: {now_str}"))
    body.append(p(f"Critérios de pesquisa: 3 buscas separadas (teor, nome da parte, nome da advogada)"))
    body.append(p(f"Status da coleta: {status_label}", bold=True, color="DC2626" if search_run.status != "complete" else "16A34A"))
    body.append(p(f"Responsável pela conferência: {operator_name}"))
    if search_run.errors:
        body.append(callout_box("OCORRÊNCIAS / FALHAS NA COLETA:", search_run.errors, hex_color="FEE2E2", text_color="991B1B"))

    body.append(p("\nSUMÁRIO EXECUTIVO DE COMUNICAÇÕES DO DIA:", bold=True))
    body.append(callout_box(
        f"Total localizado: {search_run.total_found} | Deduplicadas: {total}",
        f"• Urgentes (0 a 2 dias): {urgent_count}\n"
        f"• Atenção (3 a 5 dias): {attention_count}\n"
        f"• No horizonte (> 5 dias): {horizon_count}\n"
        f"• A conferir (sem prazo ou regra pendente): {pending_count}",
        hex_color="FEF3C7", text_color="92400E"
    ))

    # Highlight "A conferir" section prominently
    pending_items = [c for c in comms if not c.proposed_due_date or c.status == "pending_review"]
    if pending_items:
        body.append(p("\nSEÇÃO EM DESTAQUE: ITENS A CONFERIR PELA CONTROLADORIA", bold=True, color="DC2626"))
        body.append(p("Comunicações que exigem conferência humana de prazo, regra ou vinculação a caso:\n"))
        for item in pending_items:
            criteria_str = ", ".join(item.matched_fields) if item.matched_fields else "—"
            box_text = (
                f"Processo: {item.case_number} ({item.court} · {item.court_unit})\n"
                f"Partes: {item.parties or 'Não informadas'}\n"
                f"Critérios de encontro: {criteria_str}\n"
                f"Menção de prazo: {item.deadline_text}\n"
                f"Resumo: {item.content_summary}\n"
                f"Pasta vinculada: {item.matter.title if item.matter else 'Aguardando vinculação'}"
            )
            body.append(callout_box(f"[A CONFERIR] {item.communication_id}", box_text, hex_color="F1F5F9", text_color="334155"))

    # Communications grouped by court
    body.append(p("\nCOMUNICAÇÕES POR TRIBUNAL / COMARCA", bold=True))
    for court, items in courts_map.items():
        body.append(p(f"\n{court} ({len(items)} comunicação/ões)", bold=True, color="1E3A8A"))
        for c in items:
            days = (c.proposed_due_date - search_run.base_date).days if c.proposed_due_date else None
            if days is not None and days <= 2:
                urgency_badge = f"[URGENTE: {days} dia(s)]"
                bg_color = "FEE2E2"
                txt_color = "991B1B"
            elif days is not None and days <= 5:
                urgency_badge = f"[ATENÇÃO: {days} dias]"
                bg_color = "FEF3C7"
                txt_color = "92400E"
            elif days is not None:
                urgency_badge = f"[NO HORIZONTE: {days} dias]"
                bg_color = "DCFCE7"
                txt_color = "166534"
            else:
                urgency_badge = "[A CONFERIR]"
                bg_color = "F1F5F9"
                txt_color = "475569"

            due_str = c.proposed_due_date.strftime('%d/%m/%Y') if c.proposed_due_date else "Pendente de validação"
            card_text = (
                f"Identificador: {c.communication_id} | Critérios: {', '.join(c.matched_fields)}\n"
                f"Vara/Unidade: {c.court_unit or '—'}\n"
                f"Partes: {c.parties or '—'}\n"
                f"Vencimento sugerido: {due_str} ({c.deadline_text})\n"
                f"Teor/Resumo: {c.content_summary}\n"
                f"Caso no Jumbi: {c.matter.title if c.matter else 'Não vinculado'}"
            )
            body.append(callout_box(f"{urgency_badge} {c.case_number}", card_text, hex_color=bg_color, text_color=txt_color))

    body_xml = "".join(body) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
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
