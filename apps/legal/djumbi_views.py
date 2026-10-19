"""
Views interativas (HTMX + Executive High-Density UI) para os módulos portados do DJUMBI:
- Contadoria Judicial, Motor de Prazos CPC/2015 & Prescrição Intercorrente
- Banco de Peças & Editor Rico Quill com Interpolação Dinâmica + Chancela Digital SHA-256
- Painel de Correição Interna, Validador Oficial CNJ (Módulo 97), Litispendência & Classificador IA
"""

from __future__ import annotations

import csv
import html
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.services import member_has_module
from .djumbi_engine import (
     MODELOS_PECAS_DJUMBI,
    AssinaturaDigitalSha256,
    CalculoPrazoEngine,
    CnjValidator,
    ContadoriaEngine,
    CorreicaoEngine,
    HeuristicIaClassifier,
    InterpoladorMinutasEngine,
    LitispendenciaEngine,
)
from .models import Deadline, Document, Matter, Task
from .services import add_document_version, audit, can_write, visible_matters
from .views import can_edit, organization_required


def _parse_date(val: str | None, fallback: date | None = None) -> date:
    if not val:
        return fallback or timezone.localdate()
    try:
        return date.fromisoformat(str(val).strip())
    except ValueError:
        return fallback or timezone.localdate()


def _parse_decimal(val: str | None, fallback: str = "0.00") -> Decimal:
    if not val:
        return Decimal(fallback)
    cleaned = str(val).strip().replace("R$", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal(fallback)


@organization_required
@require_http_methods(["GET", "POST"])
def contadoria_prazos_hub(request):
    """
    Hub unificado:
    1) Motor Determinístico de Prazos Processuais CPC/2015 & Lei 11.419/06 (com agendamento direto na Pasta)
    2) Calculadora de Contadoria Judicial (SELIC Tema 1.076 / IPCA-E / INPC / IGP-M + Planilha CSV)
    3) Motor de Prescrição & Decadência (Intercorrente Tema 566 STJ / Quinquenal / Decadência Previdenciária 10 anos)
    """
    if hasattr(request, "membership") and not member_has_module(request.membership, "deadlines"):
        raise PermissionDenied("Seu perfil não possui acesso ao módulo de Prazos e Contadoria.")

    hoje = timezone.localdate()
    matters = visible_matters(request.user, request.organization).select_related("client").order_by("-created_at")[:100]

    data = request.POST if request.method == "POST" else request.GET
    action = data.get("action", "calcular_prazo")

    # Estado padrão do Motor de Prazos CPC
    data_pub = _parse_date(data.get("data_publicacao"), hoje)
    dias_prazo = int(data.get("quantidade_dias") or 15)
    tipo_contagem = data.get("tipo_contagem") or "DIAS_UTEIS"
    usar_janela_pje = bool(data.get("usar_janela_ciencia_pje"))
    suspender_recesso = data.get("suspender_recesso_cpc", "1") != "0"
    em_dobro = bool(data.get("em_dobro"))

    resultado_prazo = CalculoPrazoEngine.calcular(
        data_publicacao_ou_expedicao=data_pub,
        quantidade_dias=dias_prazo,
        tipo_contagem=tipo_contagem,
        usar_janela_ciencia_pje=usar_janela_pje,
        suspender_recesso_cpc=suspender_recesso,
        em_dobro=em_dobro,
    )

    # Ação: Agendar Prazo Fatal diretamente em uma Pasta Jurídica
    if request.method == "POST" and action == "agendar_prazo_pasta":
        if not can_edit(request):
            raise PermissionDenied("Seu perfil permite apenas consulta.")
        matter_id = data.get("matter_id")
        titulo_prazo = (data.get("titulo_prazo") or f"Prazo Processual ({dias_prazo} dias úteis — CPC)").strip()
        matter = get_object_or_404(visible_matters(request.user, request.organization), pk=matter_id)
        resumo_memoria = (
            f"Calculado pelo Motor Determinístico CPC/2015 (JUMBI/DJUMBI).\n"
            f"Data base/publicação: {resultado_prazo['data_publicacao_ou_expedicao'].strftime('%d/%m/%Y')} | "
            f"Ciência: {resultado_prazo['data_ciencia'].strftime('%d/%m/%Y')} ({resultado_prazo['modo_ciencia']}) | "
            f"Termo Inicial: {resultado_prazo['termo_inicial'].strftime('%d/%m/%Y')} | "
            f"Prazo: {resultado_prazo['quantidade_dias_efetivos']} ({resultado_prazo['tipo_contagem']}) | "
            f"Vencimento Fatal: {resultado_prazo['data_fatal'].strftime('%d/%m/%Y')}."
        )
        deadline = Deadline.objects.create(
            organization=request.organization,
            matter=matter,
            title=titulo_prazo,
            source=resumo_memoria,
            due_date=resultado_prazo["data_fatal"],
            internal_date=resultado_prazo["prazo_interno"],
            owner=request.user,
            kind=Deadline.Kind.COURT,
        )
        if data.get("criar_tarefa_vinculada") == "1":
            Task.objects.create(
                organization=request.organization,
                matter=matter,
                deadline=deadline,
                title=f"[Minuta/Cumprimento] {titulo_prazo}",
                description=resumo_memoria,
                owner=request.user,
                due_date=resultado_prazo["prazo_interno"],
                internal_due_date=resultado_prazo["prazo_interno"],
                priority=Task.Priority.HIGH,
            )
        audit(
            organization=request.organization,
            actor=request.user,
            action="deadline.created_from_calculator",
            obj=deadline,
            description=f"Prazo agendado via Motor Determinístico CPC para {deadline.due_date.isoformat()}.",
        )
        messages.success(
            request,
            f"Prazo '{deadline.title}' agendado na pasta '{matter.title}' com vencimento fatal em {deadline.due_date.strftime('%d/%m/%Y')}!",
        )
        return redirect("legal:detail", pk=matter.pk)

    # Estado padrão da Contadoria Judicial
    valor_orig = _parse_decimal(data.get("valor_original"), "10000.00")
    if valor_orig <= 0:
        valor_orig = Decimal("10000.00")
    dt_ini_cont = _parse_date(data.get("data_inicio_cont"), date(hoje.year - 1, hoje.month, 1))
    dt_fim_cont = _parse_date(data.get("data_fim_cont"), hoje)
    indexador = data.get("indexador") or "SELIC"
    juros_m = _parse_decimal(data.get("juros_mensal_percent"), "1.0")
    multa_p = _parse_decimal(data.get("multa_percent"), "10.0")
    hon_p = _parse_decimal(data.get("honorarios_percent"), "10.0")

    resultado_contadoria = ContadoriaEngine.calcular_debito(
        valor_original=valor_orig,
        data_inicio=dt_ini_cont,
        data_fim=dt_fim_cont,
        indexador=indexador,
        juros_mensal_percent=juros_m,
        multa_percent=multa_p,
        honorarios_percent=hon_p,
    )

    if data.get("exportar_csv") == "1":
        buffer = io.StringIO()
        buffer.write("\ufeff")
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(["MEMÓRIA DE CÁLCULO — CONTADORIA JUDICIAL JUMBI"])
        writer.writerow(["Escritório", request.organization.name])
        writer.writerow(["Data de Emissão", timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M")])
        writer.writerow([])
        writer.writerow(["Rubrica", "Detalhamento / Base Legal", "Valor (R$)"])
        writer.writerow(["Valor Principal Originário", f"Termo inicial: {dt_ini_cont.strftime('%d/%m/%Y')}", f"{resultado_contadoria['valor_original']:.2f}"])
        writer.writerow(["Correção Monetária", resultado_contadoria["indexador_nome"], f"{resultado_contadoria['valor_correcao']:.2f}"])
        writer.writerow(["Valor Principal Corrigido", f"{resultado_contadoria['meses']} competências mensais", f"{resultado_contadoria['valor_corrigido']:.2f}"])
        writer.writerow(["Juros Moratórios", resultado_contadoria["regra_juros"], f"{resultado_contadoria['valor_juros']:.2f}"])
        writer.writerow(["Multa Processual / Contratual", f"{resultado_contadoria['multa_percent']}% (Art. 523 §1º CPC)", f"{resultado_contadoria['valor_multa']:.2f}"])
        writer.writerow(["Honorários Advocatícios", f"{resultado_contadoria['honorarios_percent']}% (Art. 85 / 523 CPC)", f"{resultado_contadoria['valor_honorarios']:.2f}"])
        writer.writerow(["TOTAL LÍQUIDO ATUALIZADO", f"Termo final: {dt_fim_cont.strftime('%d/%m/%Y')}", f"{resultado_contadoria['valor_total']:.2f}"])

        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="memoria-calculo-jumbi-{hoje.isoformat()}.csv"'
        return response

    # Estado padrão do Motor de Prescrição & Decadência
    modalidade_presc = data.get("modalidade_prescricao") or "INTERCORRENTE_LEF_CPC"
    dt_marco_presc = _parse_date(data.get("data_marco_prescricao"), date(hoje.year - 4, hoje.month, hoje.day))
    dt_interrup_raw = (data.get("data_interrupcao_prescricao") or "").strip()
    dt_interrup_presc = _parse_date(dt_interrup_raw) if dt_interrup_raw else None

    resultado_prescricao = ContadoriaEngine.calcular_prescricao(
        modalidade=modalidade_presc,
        data_marco_inicial=dt_marco_presc,
        data_ultima_interrupcao=dt_interrup_presc,
        data_referencia=hoje,
    )

    context = {
        "title": "Contadoria Judicial, Prazos CPC & Prescrição",
        "page_title": "Contadoria Judicial & Motor de Prazos CPC/2015",
        "active_nav": "contadoria_prazos",
        "matters": matters,
        "can_edit": can_edit(request),
        "resultado_prazo": resultado_prazo,
        "resultado_contadoria": resultado_contadoria,
        "resultado_prescricao": resultado_prescricao,
        "indexadores": ContadoriaEngine.INDEXADORES,
        "active_action": action,
    }
    return render(request, "legal/djumbi_contadoria_prazos.html", context)


@organization_required
@require_http_methods(["GET", "POST"])
def pecas_minutas_hub(request):
    """
    Banco de Peças & Editor Rico Quill com Interpolação Dinâmica de Variáveis da Pasta
    e Chancela de Assinatura Eletrônica SHA-256 (Lei 14.063/2020) com arquivamento direto na Pasta.
    """
    if hasattr(request, "membership") and not member_has_module(request.membership, "documents"):
        raise PermissionDenied("Seu perfil não possui acesso ao módulo de Documentos e Peças.")

    matters = visible_matters(request.user, request.organization).select_related("client", "owner").prefetch_related("court_cases").order_by("-created_at")[:100]
    data = request.POST if request.method == "POST" else request.GET

    selected_matter_id = data.get("matter_id")
    selected_matter = None
    if selected_matter_id and str(selected_matter_id).isdigit():
        selected_matter = visible_matters(request.user, request.organization).select_related("client", "owner").filter(pk=int(selected_matter_id)).first()
    if not selected_matter and matters:
        selected_matter = matters[0]

    modelo_key = data.get("modelo_key") or "contestacao_cpc"
    if modelo_key not in MODELOS_PECAS_DJUMBI:
        modelo_key = "contestacao_cpc"
    modelo_atual = MODELOS_PECAS_DJUMBI[modelo_key]

    variaveis = InterpoladorMinutasEngine.extrair_variaveis_pasta(
        selected_matter, organization=request.organization, user=request.user
    )

    conteudo_editor = data.get("conteudo_html")
    if not conteudo_editor or data.get("action") == "interpolar":
        conteudo_editor = InterpoladorMinutasEngine.interpolar(modelo_atual["html"], variaveis)

    recibo_assinatura = None
    documento_salvo = None

    if request.method == "POST" and data.get("action") == "assinar_salvar":
        if not can_edit(request):
            raise PermissionDenied("Seu perfil permite apenas consulta.")
        titulo_peca = (data.get("titulo_peca") or modelo_atual["titulo"]).strip()
        signatario_nome = request.user.get_full_name() or request.user.email
        recibo_assinatura = AssinaturaDigitalSha256.assinar_conteudo(
            conteudo_editor, signatario=signatario_nome, organizacao_nome=request.organization.name
        )
        conteudo_editor = recibo_assinatura["conteudo_assinado"]

        if selected_matter and data.get("arquivar_na_pasta") == "1" and can_write(request.user, request.organization):
            # Converte o HTML assinado em texto estruturado e preserva no cofre privado da pasta (Document + DocumentVersion)
            texto_limpo = re.sub(r"<br\s*/?>|</p>|</h2>|</h3>|</h4>|</div>", "\n", conteudo_editor)
            texto_limpo = html.unescape(re.sub(r"<[^>]+>", "", texto_limpo)).strip()
            cabecalho_txt = (
                f"========================================================================\n"
                f"{request.organization.name.upper()} — PEÇA PROCESSUAL ASSINADA DIGITALMENTE\n"
                f"Título: {titulo_peca}\n"
                f"Pasta: {selected_matter.title}\n"
                f"Código de Verificação: {recibo_assinatura['codigo_verificacao']}\n"
                f"Hash Criptográfico SHA-256: {recibo_assinatura['hash_sha256']}\n"
                f"Data/Hora da Assinatura: {recibo_assinatura['timestamp']}\n"
                f"========================================================================\n\n"
                f"{texto_limpo}\n"
            )
            doc_obj, _ = Document.objects.get_or_create(
                organization=request.organization,
                matter=selected_matter,
                title=titulo_peca,
                defaults={"kind": "Peça Processual Assinada (SHA-256)", "created_by": request.user},
            )
            safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", titulo_peca.lower()).strip("-")[:50] or "peca-juridica"
            arquivo_txt = ContentFile(cabecalho_txt.encode("utf-8"), name=f"{safe_slug}.txt")
            versao = add_document_version(document=doc_obj, actor=request.user, file=arquivo_txt)
            documento_salvo = {"document": doc_obj, "version": versao}
            messages.success(
                request,
                f"Peça '{titulo_peca}' chancelada com SHA-256 ({recibo_assinatura['codigo_verificacao']}) e arquivada na pasta '{selected_matter.title}' (v{versao.number})!",
            )
        else:
            messages.success(
                request,
                f"Chancela Eletrônica SHA-256 gerada com sucesso ({recibo_assinatura['codigo_verificacao']})!",
            )

    context = {
        "title": "Banco de Peças, Editor Rico & Chancela SHA-256",
        "page_title": "Banco de Peças & Editor Dinâmico com Assinatura SHA-256",
        "active_nav": "pecas_minutas",
        "matters": matters,
        "selected_matter": selected_matter,
        "modelos": MODELOS_PECAS_DJUMBI,
        "modelo_key": modelo_key,
        "modelo_atual": modelo_atual,
        "variaveis": variaveis,
        "conteudo_editor": conteudo_editor,
        "recibo_assinatura": recibo_assinatura,
        "documento_salvo": documento_salvo,
        "can_edit": can_edit(request),
    }
    return render(request, "legal/djumbi_pecas_minutas.html", context)


@organization_required
@require_http_methods(["GET", "POST"])
def correicao_ia_hub(request):
    """
    Painel de Correição Interna do Escritório + Validador Oficial CNJ (Módulo 97)
    + Detector de Litispendência/Prevenção + Classificador Heurístico IA de Publicações.
    """
    if hasattr(request, "membership") and not member_has_module(request.membership, "cases"):
        raise PermissionDenied("Seu perfil não possui acesso ao módulo de Processos e Correição.")

    data = request.POST if request.method == "POST" else request.GET
    relatorio_correicao = CorreicaoEngine.executar_correicao(request.organization)

    # Triagem Heurística IA de Intimações / Publicações
    texto_ia = data.get("texto_intimacao") or (
        "INTIMAÇÃO: Fica a parte autora intimada para, no prazo legal de 15 (quinze) dias úteis, "
        "manifestar-se sobre o laudo pericial médico juntado aos autos da ação previdenciária em face do INSS (Lei 8.213/91)."
    )
    resultado_ia = HeuristicIaClassifier.classificar_texto(texto_ia)

    # Validador CNJ & Detector de Litispendência
    numero_cnj_input = data.get("numero_cnj") or "0001234-55.2025.8.06.0001"
    cliente_busca = data.get("cliente_busca") or ""
    documento_busca = data.get("documento_busca") or ""
    area_busca = data.get("area_busca") or ""

    resultado_cnj = CnjValidator.inspect(numero_cnj_input)
    alertas_litispendencia = LitispendenciaEngine.analisar_acervo(
        request.organization,
        client_name=cliente_busca,
        document=documento_busca,
        cnj_number=numero_cnj_input if resultado_cnj["is_valid"] else "",
        area=area_busca,
    )

    context = {
        "title": "Correição Interna, Validador CNJ & Triagem IA",
        "page_title": "Correição do Acervo, Validador CNJ & Triagem IA",
        "active_nav": "correicao_ia",
        "correicao": relatorio_correicao,
        "texto_ia": texto_ia,
        "resultado_ia": resultado_ia,
        "numero_cnj_input": numero_cnj_input,
        "cliente_busca": cliente_busca,
        "documento_busca": documento_busca,
        "area_busca": area_busca,
        "resultado_cnj": resultado_cnj,
        "alertas_litispendencia": alertas_litispendencia,
        "can_edit": can_edit(request),
    }
    return render(request, "legal/djumbi_correicao_ia.html", context)
