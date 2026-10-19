"""
Motores Determinísticos e Inteligência Jurídica portados do ecossistema DJUMBI:
1. CnjValidator (Validação Oficial CNJ Módulo 97 Base 10 + Dedução de Tribunal/Ramo)
2. CalculoPrazoEngine (Motor Determinístico CPC/2015 Art. 219, 220 Recesso, 224 + Lei 11.419/06)
3. ContadoriaEngine (Atualização Monetária SELIC Tema 1.076 STJ / IPCA-E / INPC + Prescrição/Decadência Tema 566 STJ)
4. HeuristicIaClassifier & LitispendenciaEngine (Triagem NLP de Intimações e Detector de Litispendência/Prevenção)
5. InterpoladorMinutasEngine, AssinaturaDigitalSha256 & CorreicaoEngine (Banco de Peças Quill, Hash SHA-256 e Correição Interna)
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.utils import timezone


# ==============================================================================
# 1. VALIDADOR OFICIAL CNJ (MÓDULO 97 BASE 10 - RESOLUÇÃO CNJ Nº 65/2008)
# ==============================================================================

class CnjValidator:
    """Validador determinístico da Numeração Única CNJ (NNNNNNN-DD.AAAA.J.TR.OOOO)."""

    CNJ_REGEX = re.compile(r"^(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})$")

    RAMOS_JUSTICA = {
        "1": "Supremo Tribunal Federal (STF)",
        "2": "Conselho Nacional de Justiça (CNJ)",
        "3": "Superior Tribunal de Justiça (STJ)",
        "4": "Justiça Federal",
        "5": "Justiça do Trabalho",
        "6": "Justiça Eleitoral",
        "7": "Justiça Militar da União",
        "8": "Justiça dos Estados e do Distrito Federal",
        "9": "Justiça Militar Estadual",
    }

    TRIBUNAIS_ESTADUAIS = {
        "01": "TJAC", "02": "TJAL", "03": "TJAP", "04": "TJAM", "05": "TJBA",
        "06": "TJCE", "07": "TJDF", "08": "TJES", "09": "TJGO", "10": "TJMA",
        "11": "TJMT", "12": "TJMS", "13": "TJMG", "14": "TJPA", "15": "TJPB",
        "16": "TJPR", "17": "TJPE", "18": "TJPI", "19": "TJRJ", "20": "TJRN",
        "21": "TJRS", "22": "TJRO", "23": "TJRR", "24": "TJSC", "25": "TJSE",
        "26": "TJSP", "27": "TJTO",
    }

    @classmethod
    def clean_digits(cls, value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"\D", "", str(value))

    @classmethod
    def format_cnj(cls, value: str | None) -> str:
        digits = cls.clean_digits(value)
        if len(digits) != 20:
            return (value or "").strip()
        return f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13:14]}.{digits[14:16]}.{digits[16:20]}"

    @classmethod
    def is_valid(cls, value: str | None) -> bool:
        if not value:
            return False
        formatted = cls.format_cnj(value)
        match = cls.CNJ_REGEX.match(formatted)
        if not match:
            return False
        n, dd, aaaa, j, tr, oooo = match.groups()
        try:
            bloco_int = int(f"{n}{aaaa}{j}{tr}{oooo}00")
            resto = bloco_int % 97
            digito_esperado = 98 - resto
            return digito_esperado == int(dd)
        except ValueError:
            return False

    @classmethod
    def calculate_expected_dd(cls, value: str | None) -> str | None:
        digits = cls.clean_digits(value)
        if len(digits) != 20:
            return None
        n = digits[0:7]
        aaaa = digits[9:13]
        j = digits[13:14]
        tr = digits[14:16]
        oooo = digits[16:20]
        try:
            bloco_int = int(f"{n}{aaaa}{j}{tr}{oooo}00")
            digito_esperado = 98 - (bloco_int % 97)
            return f"{digito_esperado:02d}"
        except ValueError:
            return None

    @classmethod
    def inspect(cls, value: str | None) -> dict[str, Any]:
        raw = (value or "").strip()
        digits = cls.clean_digits(raw)
        formatted = cls.format_cnj(raw)
        valid = cls.is_valid(raw)
        if len(digits) != 20:
            return {
                "raw": raw,
                "formatted": formatted,
                "is_valid": False,
                "error": f"O número possui {len(digits)} dígitos (o padrão CNJ exige 20 dígitos).",
                "year": None,
                "branch": "Não identificado",
                "tribunal": "Não identificado",
                "origin_code": None,
                "expected_dd": None,
            }
        n = digits[0:7]
        dd = digits[7:9]
        aaaa = digits[9:13]
        j = digits[13:14]
        tr = digits[14:16]
        oooo = digits[16:20]
        expected_dd = cls.calculate_expected_dd(digits)
        branch = cls.RAMOS_JUSTICA.get(j, "Ramo Especial")
        tribunal = "Órgão Jurisdicional"
        if j == "8":
            tribunal = cls.TRIBUNAIS_ESTADUAIS.get(tr, f"TJ Estadual ({tr})")
        elif j == "4":
            tribunal = f"TRF da {int(tr)}ª Região" if tr.isdigit() and int(tr) > 0 else "Justiça Federal"
        elif j == "5":
            tribunal = "TST" if tr == "00" else f"TRT da {int(tr)}ª Região"
        elif j == "6":
            tribunal = "TSE" if tr == "00" else f"TRE ({tr})"
        elif j in {"1", "2", "3"}:
            tribunal = branch

        return {
            "raw": raw,
            "formatted": formatted,
            "is_valid": valid,
            "error": "" if valid else f"Dígito verificador inválido (informado '{dd}', esperado '{expected_dd}' pelo Módulo 97).",
            "sequential": n,
            "dd": dd,
            "expected_dd": expected_dd,
            "year": int(aaaa) if aaaa.isdigit() else None,
            "branch_code": j,
            "branch": branch,
            "tribunal_code": tr,
            "tribunal": tribunal,
            "origin_code": oooo,
        }


# ==============================================================================
# 2. MOTOR DETERMINÍSTICO DE PRAZOS PROCESSUAIS CPC/2015 & LEI 11.419/2006
# ==============================================================================

FERIADOS_NACIONAIS_FIXOS = {
    (1, 1): "Confraternização Universal (Feriado Nacional)",
    (4, 21): "Tiradentes (Feriado Nacional)",
    (5, 1): "Dia do Trabalho (Feriado Nacional)",
    (8, 11): "Dia da Advocacia / Pendura (Feriado Forense)",
    (9, 7): "Independência do Brasil (Feriado Nacional)",
    (10, 12): "Nossa Senhora Aparecida (Feriado Nacional)",
    (11, 1): "Dia de Todos os Santos (Feriado Forense)",
    (11, 2): "Finados (Feriado Nacional)",
    (11, 15): "Proclamação da República (Feriado Nacional)",
    (11, 20): "Dia Nacional de Zumbi e da Consciência Negra",
    (12, 8): "Dia da Justiça (Feriado Forense - Dec.-Lei 8.292/45)",
    (12, 25): "Natal (Feriado Nacional)",
}


class CalculoPrazoEngine:
    """
    Motor determinístico de prazos processuais (CPC/2015 Art. 219, 220, 224 e Lei 11.419/2006).
    Gera memória de cálculo auditável dia a dia.
    """

    @staticmethod
    def is_recesso_forense_art220_cpc(d: date) -> bool:
        """Art. 220 CPC/2015: Suspensão dos prazos processuais entre 20/12 e 20/01."""
        return (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 20)

    @classmethod
    def get_holiday_reason(cls, d: date, custom_holidays: set[date] | None = None) -> str | None:
        if custom_holidays and d in custom_holidays:
            return "Feriado Local / Suspensão de Expediente Forense"
        return FERIADOS_NACIONAIS_FIXOS.get((d.month, d.day))

    @classmethod
    def is_dia_util_forense(
        cls,
        d: date,
        *,
        suspender_recesso: bool = True,
        custom_holidays: set[date] | None = None,
    ) -> tuple[bool, str]:
        if suspender_recesso and cls.is_recesso_forense_art220_cpc(d):
            return False, "Suspenso — Recesso Forense (Art. 220 CPC/2015: 20/12 a 20/01)"
        if d.weekday() == 5:
            return False, "Sábado — Sem expediente forense (Art. 219 / 224 CPC)"
        if d.weekday() == 6:
            return False, "Domingo — Sem expediente forense (Art. 219 / 224 CPC)"
        holiday = cls.get_holiday_reason(d, custom_holidays)
        if holiday:
            return False, f"Feriado — {holiday}"
        return True, "Dia útil forense computado (Art. 219 CPC)"

    @classmethod
    def calcular(
        cls,
        *,
        data_publicacao_ou_expedicao: date,
        quantidade_dias: int,
        tipo_contagem: str = "DIAS_UTEIS",
        usar_janela_ciencia_pje: bool = False,
        data_ciencia_efetiva: date | None = None,
        suspender_recesso_cpc: bool = True,
        em_dobro: bool = False,
        feriados_extras: list[date] | None = None,
    ) -> dict[str, Any]:
        """
        Calcula o termo inicial, data limite de ciência (Lei 11.419/06), prazo interno e vencimento fatal,
        retornando memória de cálculo detalhada passo a passo.
        """
        custom_holidays = set(feriados_extras or [])
        dias_base = max(1, int(quantidade_dias))
        dias_efetivos = dias_base * 2 if em_dobro else dias_base
        memoria: list[dict[str, str]] = []

        # 1. Controle de Ciência (Lei 11.419/2006 - Art. 5º § 3º: 10 dias corridos da expedição)
        limite_ciencia = data_publicacao_ou_expedicao + timedelta(days=10)
        while True:
            util, motivo = cls.is_dia_util_forense(
                limite_ciencia, suspender_recesso=False, custom_holidays=custom_holidays
            )
            if util:
                break
            limite_ciencia += timedelta(days=1)

        if usar_janela_ciencia_pje:
            if data_ciencia_efetiva and data_ciencia_efetiva <= limite_ciencia:
                data_ciencia = data_ciencia_efetiva
                modo_ciencia = "Ciência Expressa antes do fim do decêndio (Lei 11.419/06)"
            else:
                data_ciencia = limite_ciencia
                modo_ciencia = "Ciência Tácita / Automática no 10º dia corrido (Art. 5º §3º Lei 11.419/06)"
            memoria.append({
                "data": data_publicacao_ou_expedicao.strftime("%d/%m/%Y"),
                "etapa": "Expedição no PJe/Domicílio",
                "status": "MARCO ZERO",
                "detalhe": f"Expedição eletrônica. Limite dos 10 dias de leitura: {limite_ciencia.strftime('%d/%m/%Y')}.",
            })
            memoria.append({
                "data": data_ciencia.strftime("%d/%m/%Y"),
                "etapa": "Data da Ciência",
                "status": "CIÊNCIA",
                "detalhe": f"{modo_ciencia}. Exclui-se o dia do começo (Art. 224 CPC).",
            })
        else:
            data_ciencia = data_publicacao_ou_expedicao
            modo_ciencia = "Publicação no DJe / Intimação direta (Art. 224 CPC)"
            memoria.append({
                "data": data_ciencia.strftime("%d/%m/%Y"),
                "etapa": "Publicação / Intimação",
                "status": "EXCLUÍDO",
                "detalhe": "Dia do começo excluído da contagem (Art. 224 caput CPC/2015).",
            })

        # 2. Prorrogação do termo inicial se a ciência caiu em dia não útil
        cursor = data_ciencia + timedelta(days=1)
        while True:
            util, motivo = cls.is_dia_util_forense(
                cursor, suspender_recesso=suspender_recesso_cpc, custom_holidays=custom_holidays
            )
            if util:
                break
            memoria.append({
                "data": cursor.strftime("%d/%m/%Y"),
                "etapa": "Aguardando Termo Inicial",
                "status": "SUSPENSO",
                "detalhe": f"Início prorrogado para o 1º dia útil seguinte (Art. 224 §1º CPC) — {motivo}",
            })
            cursor += timedelta(days=1)

        termo_inicial = cursor

        # 3. Contagem dos dias (Úteis vs. Corridos)
        dias_contados = 0
        cursor = termo_inicial
        while dias_contados < dias_efetivos:
            util, motivo = cls.is_dia_util_forense(
                cursor, suspender_recesso=suspender_recesso_cpc, custom_holidays=custom_holidays
            )
            if tipo_contagem == "DIAS_UTEIS":
                if util:
                    dias_contados += 1
                    memoria.append({
                        "data": cursor.strftime("%d/%m/%Y"),
                        "etapa": f"{dias_contados}º dia útil",
                        "status": "COMPUTADO",
                        "detalhe": motivo,
                    })
                else:
                    memoria.append({
                        "data": cursor.strftime("%d/%m/%Y"),
                        "etapa": "Não computado",
                        "status": "SUSPENSO",
                        "detalhe": motivo,
                    })
            else:
                # Dias corridos (ainda respeita recesso se marcado, e prorroga o vencimento final se cair em feriado/fim de semana)
                if suspender_recesso_cpc and cls.is_recesso_forense_art220_cpc(cursor):
                    memoria.append({
                        "data": cursor.strftime("%d/%m/%Y"),
                        "etapa": "Recesso Forense",
                        "status": "SUSPENSO",
                        "detalhe": "Suspenso — Recesso Forense (Art. 220 CPC)",
                    })
                else:
                    dias_contados += 1
                    memoria.append({
                        "data": cursor.strftime("%d/%m/%Y"),
                        "etapa": f"{dias_contados}º dia corrido",
                        "status": "COMPUTADO",
                        "detalhe": "Dia corrido computado",
                    })
            if dias_contados < dias_efetivos:
                cursor += timedelta(days=1)

        # 4. Se o vencimento cair em dia não útil (em contagem de dias corridos), prorroga para o próximo dia útil (Art. 224 §1º CPC)
        while True:
            util, motivo = cls.is_dia_util_forense(
                cursor, suspender_recesso=suspender_recesso_cpc, custom_holidays=custom_holidays
            )
            if util:
                break
            cursor += timedelta(days=1)
            util_next, motivo_next = cls.is_dia_util_forense(
                cursor, suspender_recesso=suspender_recesso_cpc, custom_holidays=custom_holidays
            )
            memoria.append({
                "data": cursor.strftime("%d/%m/%Y"),
                "etapa": "Prorrogação de Vencimento",
                "status": "PRORROGADO" if util_next else "SUSPENSO",
                "detalhe": f"Prorrogação do termo final para o primeiro dia útil (Art. 224 §1º CPC) — {motivo_next}",
            })

        data_fatal = cursor
        prazo_interno = data_fatal - timedelta(days=2)
        while prazo_interno > termo_inicial and prazo_interno.weekday() in (5, 6):
            prazo_interno -= timedelta(days=1)

        hoje = timezone.localdate()
        dias_restantes = (data_fatal - hoje).days

        return {
            "data_publicacao_ou_expedicao": data_publicacao_ou_expedicao,
            "limite_ciencia_pje": limite_ciencia,
            "data_ciencia": data_ciencia,
            "modo_ciencia": modo_ciencia,
            "termo_inicial": termo_inicial,
            "data_fatal": data_fatal,
            "prazo_interno": prazo_interno,
            "quantidade_dias_base": dias_base,
            "quantidade_dias_efetivos": dias_efetivos,
            "em_dobro": em_dobro,
            "tipo_contagem": tipo_contagem,
            "dias_restantes": dias_restantes,
            "memoria_calculo": memoria,
        }


# ==============================================================================
# 3. CONTADORIA JUDICIAL (SELIC TEMA 1.076 STJ / IPCA-E / INPC) & PRESCRIÇÃO
# ==============================================================================

class ContadoriaEngine:
    """
    Motor de atualização monetária, juros, multa do Art. 523 CPC, honorários
    e prescrição/decadência (incluindo Prescrição Intercorrente Art. 40 LEF / Art. 921 CPC).
    """

    INDEXADORES = {
        "SELIC": {
            "nome": "Taxa SELIC (STJ Tema 1.076 — Engloba Correção + Juros)",
            "taxa_mensal": Decimal("0.0085"),
            "juros_separados": False,
        },
        "IPCA_E": {
            "nome": "IPCA-E (IBGE/Justiça Federal) + Juros de Mora",
            "taxa_mensal": Decimal("0.0038"),
            "juros_separados": True,
        },
        "INPC": {
            "nome": "INPC (IBGE/Previdenciário/Cível) + Juros de Mora",
            "taxa_mensal": Decimal("0.0035"),
            "juros_separados": True,
        },
        "IGPM": {
            "nome": "IGP-M (FGV/Contratual/Locatício) + Juros de Mora",
            "taxa_mensal": Decimal("0.0045"),
            "juros_separados": True,
        },
    }

    @classmethod
    def calcular_debito(
        cls,
        *,
        valor_original: Decimal,
        data_inicio: date,
        data_fim: date,
        indexador: str = "SELIC",
        juros_mensal_percent: Decimal = Decimal("1.0"),
        multa_percent: Decimal = Decimal("10.0"),
        honorarios_percent: Decimal = Decimal("10.0"),
    ) -> dict[str, Any]:
        valor_base = Decimal(str(valor_original)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if data_fim < data_inicio:
            data_fim = data_inicio

        meses = max(0, (data_fim.year - data_inicio.year) * 12 + (data_fim.month - data_inicio.month))
        idx_cfg = cls.INDEXADORES.get(indexador, cls.INDEXADORES["SELIC"])
        taxa_correcao = idx_cfg["taxa_mensal"]

        if not idx_cfg["juros_separados"]:
            # Regra STJ Tema 1.076: SELIC não cumula com juros moratórios separados
            fator_correcao = taxa_correcao * Decimal(meses)
            valor_correcao = (valor_base * fator_correcao).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            valor_corrigido = valor_base + valor_correcao
            valor_juros = Decimal("0.00")
            regra_juros = "Juros já incorporados na Taxa SELIC (Vedada cumulação — STJ Tema 1.076)"
        else:
            fator_correcao = taxa_correcao * Decimal(meses)
            valor_correcao = (valor_base * fator_correcao).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            valor_corrigido = valor_base + valor_correcao
            taxa_juros = (Decimal(str(juros_mensal_percent)) / Decimal("100")) * Decimal(meses)
            valor_juros = (valor_corrigido * taxa_juros).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            regra_juros = f"Juros simples de {juros_mensal_percent}% a.m. × {meses} meses ({taxa_juros * 100:.2f}%)"

        subtotal = valor_corrigido + valor_juros
        valor_multa = (subtotal * (Decimal(str(multa_percent)) / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        base_honorarios = subtotal + valor_multa
        valor_honorarios = (base_honorarios * (Decimal(str(honorarios_percent)) / Decimal("100"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        valor_total = (base_honorarios + valor_honorarios).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        memoria_linhas = [
            f"1. Valor Principal Originário: R$ {valor_base:,.2f}",
            f"2. Período Calculado: {data_inicio.strftime('%d/%m/%Y')} até {data_fim.strftime('%d/%m/%Y')} ({meses} competências mensais)",
            f"3. Indexador Aplicado: {idx_cfg['nome']} (+ R$ {valor_correcao:,.2f})",
            f"4. Valor Principal Corrigido: R$ {valor_corrigido:,.2f}",
            f"5. Juros Moratórios: R$ {valor_juros:,.2f} ({regra_juros})",
            f"6. Multa ({multa_percent}% — Art. 523 §1º CPC / Contratual): R$ {valor_multa:,.2f}",
            f"7. Honorários Advocatícios ({honorarios_percent}% — Art. 85 / 523 CPC): R$ {valor_honorarios:,.2f}",
            f"8. TOTAL LÍQUIDO ATUALIZADO DO DÉBITO: R$ {valor_total:,.2f}",
        ]

        return {
            "valor_original": valor_base,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "meses": meses,
            "indexador": indexador,
            "indexador_nome": idx_cfg["nome"],
            "valor_correcao": valor_correcao,
            "valor_corrigido": valor_corrigido,
            "valor_juros": valor_juros,
            "regra_juros": regra_juros,
            "multa_percent": Decimal(str(multa_percent)),
            "valor_multa": valor_multa,
            "honorarios_percent": Decimal(str(honorarios_percent)),
            "valor_honorarios": valor_honorarios,
            "valor_total": valor_total,
            "memoria_linhas": memoria_linhas,
            "memoria_texto": "\n".join(memoria_linhas),
        }

    @classmethod
    def calcular_prescricao(
        cls,
        *,
        modalidade: str,
        data_marco_inicial: date,
        data_ultima_interrupcao: date | None = None,
        data_referencia: date | None = None,
    ) -> dict[str, Any]:
        """
        Motor de Prescrição e Decadência:
        - INTERCORRENTE_LEF_CPC: 1 ano de suspensão (Art. 40 §2º LEF / Art. 921 §4º CPC) + 5 anos intercorrentes (Tema 566 STJ)
        - QUINQUENAL: 5 anos (Decreto 20.910/32 / Tributário CTN Art. 174 / Trabalhista)
        - DECADENCIA_PREVIDENCIARIA: 10 anos (Art. 103 Lei 8.213/91 — Revisão de Benefício INSS)
        - TRIENAL_CIVIL: 3 anos (Art. 206 §3º CC — Reparação Civil / Enriquecimento sem Causa)
        """
        hoje = data_referencia or timezone.localdate()
        base_date = data_ultima_interrupcao if (data_ultima_interrupcao and data_ultima_interrupcao > data_marco_inicial) else data_marco_inicial

        if modalidade == "INTERCORRENTE_LEF_CPC":
            try:
                fim_suspensao = base_date.replace(year=base_date.year + 1)
            except ValueError:
                fim_suspensao = base_date + timedelta(days=365)
            try:
                termo_final = fim_suspensao.replace(year=fim_suspensao.year + 5)
            except ValueError:
                termo_final = fim_suspensao + timedelta(days=365 * 5)
            fundamento = "Art. 40 da Lei 6.830/80 (LEF), Art. 921 §4º do CPC/2015 e Tema 566 do STJ (1 ano de suspensão + 5 anos de prescrição intercorrente)."
        elif modalidade == "DECADENCIA_PREVIDENCIARIA":
            fim_suspensao = None
            try:
                termo_final = base_date.replace(year=base_date.year + 10)
            except ValueError:
                termo_final = base_date + timedelta(days=3650)
            fundamento = "Art. 103 da Lei 8.213/91 — Prazo decadencial de 10 (dez) anos para revisão do ato de concessão/indeferimento de benefício previdenciário."
        elif modalidade == "TRIENAL_CIVIL":
            fim_suspensao = None
            try:
                termo_final = base_date.replace(year=base_date.year + 3)
            except ValueError:
                termo_final = base_date + timedelta(days=365 * 3)
            fundamento = "Art. 206, § 3º, V do Código Civil — Prescrição trienal (3 anos) para pretensão de reparação civil."
        else:
            fim_suspensao = None
            try:
                termo_final = base_date.replace(year=base_date.year + 5)
            except ValueError:
                termo_final = base_date + timedelta(days=365 * 5)
            fundamento = "Prescrição Quinquenal de 5 (cinco) anos (Art. 174 CTN / Decreto 20.910/32 / Art. 206 §5º CC)."

        dias_para_prescrever = (termo_final - hoje).days
        prescrito = hoje > termo_final
        if prescrito:
            status = "PRESCRITO / DECADENTE"
            cor = "danger"
        elif dias_para_prescrever <= 180:
            status = "RISCO CRÍTICO (< 6 MESES)"
            cor = "warning"
        elif fim_suspensao and hoje <= fim_suspensao:
            status = "EM SUSPENSÃO ANUAL (ART. 40 §1º LEF / CPC)"
            cor = "info"
        else:
            status = "PRAZO REGULAR / ATIVO"
            cor = "success"

        return {
            "modalidade": modalidade,
            "data_marco_inicial": data_marco_inicial,
            "data_ultima_interrupcao": data_ultima_interrupcao,
            "fim_suspensao_anual": fim_suspensao,
            "termo_final_prescricao": termo_final,
            "dias_restantes": dias_para_prescrever,
            "prescrito": prescrito,
            "status": status,
            "cor": cor,
            "fundamento": fundamento,
        }


# ==============================================================================
# 4. CLASSIFICADOR HEURÍSTICO IA (NLP) & DETECTOR DE LITISPENDÊNCIA
# ==============================================================================

class HeuristicIaClassifier:
    """
    Motor de triagem inteligente de publicações, intimações e peças iniciais
    portado de HeuristicIaClassifierService.java e expandido para os nichos do JUMBI.
    """

    @classmethod
    def classificar_texto(cls, texto: str | None) -> dict[str, Any]:
        if not texto or not texto.strip():
            return {
                "categoria": "Não Classificado",
                "confianca": 0,
                "explicacao": "Texto vazio ou insuficiente para triagem automatizada.",
                "prazo_sugerido_dias": 15,
                "peca_sugerida": "Petição Simples / Manifestação",
                "fundamento_legal": "Art. 218 §3º CPC",
            }

        t = texto.lower()
        score_prev = 0
        score_trab = 0
        score_trib = 0
        score_adm = 0
        score_civel = 0

        for kw, pts in [
            ("inss", 35), ("aposentadoria", 35), ("auxílio-doença", 35), ("auxilio-doenca", 35),
            ("bpc", 30), ("loas", 30), ("perícia médica", 25), ("pericia medica", 25),
            ("benefício previdenciário", 35), ("cnis", 25), ("incapacidade temporária", 30),
            ("lei 8.213", 30), ("segurado especial", 25),
        ]:
            if kw in t:
                score_prev += pts

        for kw, pts in [
            ("reclamação trabalhista", 40), ("reclamacao trabalhista", 40), ("clt", 30),
            ("fgts", 25), ("horas extras", 25), ("verbas rescisórias", 35), ("verbas rescisorias", 35),
            ("vínculo empregatício", 35), ("trt", 25), ("insalubridade", 25), ("recurso ordinário", 30),
        ]:
            if kw in t:
                score_trab += pts

        for kw, pts in [
            ("execução fiscal", 40), ("execucao fiscal", 40), ("cda", 30), ("dívida ativa", 35),
            ("iptu", 25), ("icms", 25), ("iss", 20), ("sisbajud", 30), ("penhora", 25),
            ("embargos à execução", 35), ("lei 6.830", 35), ("prescrição intercorrente", 30),
        ]:
            if kw in t:
                score_trib += pts

        for kw, pts in [
            ("mandado de segurança", 35), ("licitação", 30), ("licitacao", 30), ("servidor público", 30),
            ("processo administrativo", 25), ("improbidade", 30), ("edital", 20),
        ]:
            if kw in t:
                score_adm += pts

        for kw, pts in [
            ("dano moral", 30), ("indenização", 25), ("indenizacao", 25), ("consumidor", 25),
            ("contestação", 25), ("contestacao", 25), ("apelação", 30), ("apelacao", 30),
            ("cumprimento de sentença", 30), ("art. 523", 30), ("tutela de urgência", 25),
        ]:
            if kw in t:
                score_civel += pts

        scores = [
            ("Previdenciário & Benefícios (INSS)", score_prev, 15, "Manifestação sobre Laudo / Petição Previdenciária", "Lei 8.213/91 e CPC/2015"),
            ("Trabalhista & Reclamatória (CLT)", score_trab, 8, "Contestação Trabalhista / Recurso Ordinário", "Arts. 775 e 895 da CLT (8 dias úteis)"),
            ("Tributário & Execução Fiscal", score_trib, 30, "Exceção de Pré-Executividade / Embargos à Execução", "Lei 6.830/80 (LEF) e Art. 921 CPC"),
            ("Direito Público & Administrativo", score_adm, 15, "Mandado de Segurança / Defesa Administrativa", "Lei 12.016/2009 e CPC/2015"),
            ("Contencioso Cível & Consumidor", score_civel, 15, "Contestação Cível / Apelação / Cumprimento Art. 523", "Arts. 335, 523 e 1.009 do CPC/2015"),
        ]
        scores.sort(key=lambda item: item[1], reverse=True)
        top_cat, top_score, prazo_sugerido, peca_sugerida, fundamento = scores[0]

        # Ajuste fino de prazo por ato processual mencionado no texto
        if "embargos de declaração" in t or "embargos de declaracao" in t:
            prazo_sugerido = 5
            peca_sugerida = "Embargos de Declaração (Art. 1.022 CPC)"
            fundamento = "Art. 1.023 do CPC/2015 (Prazo de 5 dias úteis)"
        elif "emendar a inicial" in t or "emenda à inicial" in t:
            prazo_sugerido = 15
            peca_sugerida = "Petição de Emenda à Inicial (Art. 321 CPC)"
            fundamento = "Art. 321 do CPC/2015 (15 dias úteis)"
        elif "laudo pericial" in t:
            prazo_sugerido = 15
            peca_sugerida = "Manifestação sobre Laudo Pericial"
            fundamento = "Art. 477 §1º do CPC/2015 (15 dias úteis)"

        if top_score == 0:
            return {
                "categoria": "Contencioso Cível Geral",
                "confianca": 68,
                "explicacao": "Classificação padrão por ausência de termos restritos de rito especial; aplica-se a regra geral do CPC/2015.",
                "prazo_sugerido_dias": prazo_sugerido,
                "peca_sugerida": peca_sugerida,
                "fundamento_legal": fundamento,
            }

        confianca = min(99, 65 + (top_score // 2))
        return {
            "categoria": top_cat,
            "confianca": confianca,
            "explicacao": f"Identificados termos-chave de alta relevância jurídica com score {top_score} para {top_cat}.",
            "prazo_sugerido_dias": prazo_sugerido,
            "peca_sugerida": peca_sugerida,
            "fundamento_legal": fundamento,
        }


class LitispendenciaEngine:
    """
    Detector de Litispendência, Prevenção e Conflito de Interesses no acervo do escritório
    (Portado de LitispendenciaService.java).
    """

    @classmethod
    def analisar_acervo(cls, organization, *, client_name: str = "", document: str = "", cnj_number: str = "", area: str = "", exclude_matter_id: int | None = None) -> list[dict[str, Any]]:
        from apps.legal.models import CourtCase, Matter

        alertas: list[dict[str, Any]] = []
        clean_doc = re.sub(r"\D", "", document or "")
        clean_cnj = CnjValidator.clean_digits(cnj_number)

        # 1. Verifica duplicidade exata de número de processo CNJ
        if clean_cnj:
            for case in CourtCase.objects.filter(organization=organization).select_related("matter", "matter__client"):
                if exclude_matter_id and case.matter_id == exclude_matter_id:
                    continue
                if CnjValidator.clean_digits(case.number) == clean_cnj:
                    alertas.append({
                        "nivel": "CRÍTICO (100%)",
                        "similaridade": 100,
                        "tipo": "Duplicidade Exata de Processo CNJ",
                        "pasta_id": case.matter_id,
                        "pasta_titulo": case.matter.title,
                        "processo_numero": case.number,
                        "cliente": case.matter.client.name if case.matter.client else "—",
                        "detalhe": f"O processo {case.number} já está cadastrado na pasta '{case.matter.title}'.",
                    })

        # 2. Verifica pastas ativas do mesmo CPF/CNPJ ou nome similar na mesma área jurídica
        matters_qs = Matter.objects.filter(organization=organization).select_related("client")
        if exclude_matter_id:
            matters_qs = matters_qs.exclude(pk=exclude_matter_id)

        for m in matters_qs[:200]:
            if not m.client:
                continue
            m_doc = re.sub(r"\D", "", m.client.document or "")
            same_doc = bool(clean_doc and m_doc and clean_doc == m_doc)
            same_name = bool(client_name and len(client_name.strip()) >= 4 and client_name.strip().lower() in m.client.name.lower())

            if same_doc or same_name:
                same_area = bool(area and m.area and area.lower() == m.area.lower())
                sim = 92 if (same_doc and same_area) else (85 if same_doc else 78)
                alertas.append({
                    "nivel": "ALTO" if sim >= 85 else "MODERADO",
                    "similaridade": sim,
                    "tipo": "Possível Litispendência / Prevenção / Conexão (Art. 55 e 337 §3º CPC)",
                    "pasta_id": m.pk,
                    "pasta_titulo": m.title,
                    "processo_numero": ", ".join(m.court_cases.values_list("number", flat=True)) or "Sem processo",
                    "cliente": m.client.name,
                    "detalhe": f"Cliente já possui pasta ativa ('{m.title}') na área '{m.area or 'Geral'}'. Verifique prevenção ou litispendência.",
                })

        return alertas


# ==============================================================================
# 5. INTERPOLADOR DE PEÇAS & ASSINATURA DIGITAL SHA-256 + CORREIÇÃO DO ACERVO
# ==============================================================================

MODELOS_PECAS_DJUMBI = {
    "contestacao_cpc": {
        "titulo": "Contestação Cível / Fazenda / Rito Comum (Art. 335 CPC)",
        "categoria": "Contencioso Cível",
        "html": (
            "<h3>EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DO(A) {{ORGAO_JULGADOR}}</h3>"
            "<p><br></p>"
            "<p><strong>Processo nº:</strong> {{NUMERO_PROCESSO}}</p>"
            "<p><strong>Pasta Interna:</strong> {{PASTA_TITULO}} ({{AREA_JURIDICA}})</p>"
            "<p><br></p>"
            "<p><strong>{{NOME_CLIENTE}}</strong>, inscrito(a) no CPF/CNPJ sob o nº <strong>{{CPF_CNPJ}}</strong>, "
            "com endereço em {{ENDERECO_CLIENTE}}, por seu(sua) advogado(a) infra-assinado(a) ({{ADVOGADO_RESPONSAVEL}}), "
            "vem, respeitosamente, à presença de Vossa Excelência, nos termos do art. 335 e seguintes do Código de Processo Civil, "
            "apresentar sua</p>"
            "<h2>CONTESTAÇÃO</h2>"
            "<p>em face da ação movida por <strong>{{PARTE_CONTRARIA}}</strong>, pelos fatos e fundamentos jurídicos a seguir expostos:</p>"
            "<h4>I. DA TEMPESTIVIDADE E SÍNTESE DA DEMANDA</h4>"
            "<p>A presente peça é manifestamente tempestiva, observada a contagem em dias úteis prevista no art. 219 do CPC/2015.</p>"
            "<h4>II. DAS PRELIMINARES DE MÉRITO (ART. 337 DO CPC)</h4>"
            "<p>Cumpre suscitar, preliminarmente, a regularidade processual e a ausência de pressupostos que autorizem a procedência imediata do pleito autoral.</p>"
            "<h4>III. DO MÉRITO</h4>"
            "<p>No mérito, as alegações da parte autora não merecem prosperar, conforme prova documental acostada aos autos desta pasta jurídica.</p>"
            "<h4>IV. DOS PEDIDOS</h4>"
            "<p>Ante o exposto, requer o acolhimento das preliminares arguidas e, no mérito, a total improcedência dos pedidos formulados na inicial, "
            "condenando-se a parte adversa ao pagamento das custas processuais e honorários advocatícios sucumbenciais (art. 85 do CPC).</p>"
            "<p><br></p>"
            "<p>Nestes termos, pede deferimento.</p>"
            "<p>{{DATA_EXTENSO}}</p>"
            "<p><strong>{{ADVOGADO_RESPONSAVEL}}</strong><br>{{ESCRITORIO_NOME}}</p>"
        ),
    },
    "cumprimento_sentenca_523": {
        "titulo": "Cumprimento Definitivo de Sentença (Art. 523 do CPC)",
        "categoria": "Execução / Cumprimento",
        "html": (
            "<h3>EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DO(A) {{ORGAO_JULGADOR}}</h3>"
            "<p><br></p>"
            "<p><strong>Processo nº:</strong> {{NUMERO_PROCESSO}}</p>"
            "<p><br></p>"
            "<p><strong>{{NOME_CLIENTE}}</strong> (CPF/CNPJ: {{CPF_CNPJ}}), já qualificado(a) nos autos em epígrafe, "
            "por intermédio de seu patrono <strong>{{ADVOGADO_RESPONSAVEL}}</strong>, vem requerer a instauração da fase de</p>"
            "<h2>CUMPRIMENTO DE SENTENÇA (ART. 523 DO CPC/2015)</h2>"
            "<p>em face de <strong>{{PARTE_CONTRARIA}}</strong>, requerendo a intimação da parte executada para que, no prazo de 15 (quinze) dias úteis, "
            "efetue o pagamento voluntário do débito atualizado conforme Memória de Cálculo anexa, sob pena de incidência automática de "
            "multa de 10% (dez por cento) e honorários advocatícios de 10% (dez por cento), nos termos do art. 523, § 1º, do CPC, "
            "bem como expedição de ordem de bloqueio via SISBAJUD (art. 854 do CPC).</p>"
            "<p><br></p>"
            "<p>Nestes termos, pede deferimento.</p>"
            "<p>{{DATA_EXTENSO}}</p>"
            "<p><strong>{{ADVOGADO_RESPONSAVEL}}</strong><br>{{ESCRITORIO_NOME}}</p>"
        ),
    },
    "peticao_previdenciaria_inss": {
        "titulo": "Petição Inicial / Manifestação Previdenciária (Lei 8.213/91)",
        "categoria": "Previdenciário & INSS",
        "html": (
            "<h3>EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) FEDERAL DO(A) {{ORGAO_JULGADOR}}</h3>"
            "<p><br></p>"
            "<p><strong>Processo / Referência:</strong> {{NUMERO_PROCESSO}}</p>"
            "<p><strong>Segurado(a):</strong> {{NOME_CLIENTE}} — CPF: {{CPF_CNPJ}}</p>"
            "<p><strong>Endereço:</strong> {{ENDERECO_CLIENTE}}</p>"
            "<p><br></p>"
            "<h2>MANIFESTAÇÃO / REQUERIMENTO PREVIDENCIÁRIO</h2>"
            "<p>O(A) Segurado(a) acima qualificado(a), em face do <strong>INSTITUTO NACIONAL DO SEGURO SOCIAL — INSS</strong>, "
            "vem apresentar manifestação técnica acerca dos requisitos de qualidade de segurado, carência e comprovação documental "
            "constantes na pasta <strong>{{PASTA_TITULO}}</strong>, pugnando pela concessão/implantação do benefício devido desde a DER, "
            "com pagamento das parcelas vencidas acrescidas de correção monetária pelo INPC e juros moratórios (Tema 810 STF / Tema 905 STJ).</p>"
            "<p><br></p>"
            "<p>{{DATA_EXTENSO}}</p>"
            "<p><strong>{{ADVOGADO_RESPONSAVEL}}</strong><br>{{ESCRITORIO_NOME}}</p>"
        ),
    },
    "reclamatoria_trabalhista": {
        "titulo": "Manifestação / Razões Finais Trabalhistas (CLT)",
        "categoria": "Trabalhista",
        "html": (
            "<h3>EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DO TRABALHO DO(A) {{ORGAO_JULGADOR}}</h3>"
            "<p><br></p>"
            "<p><strong>Processo Trabalhista nº:</strong> {{NUMERO_PROCESSO}}</p>"
            "<p><strong>Reclamante / Cliente:</strong> {{NOME_CLIENTE}} ({{CPF_CNPJ}})</p>"
            "<p><strong>Reclamada:</strong> {{PARTE_CONTRARIA}}</p>"
            "<p><br></p>"
            "<h2>RAZÕES FINAIS E MANIFESTAÇÃO SOBRE CÁLCULOS</h2>"
            "<p>A parte autora/reclamante, nos autos da Reclamação Trabalhista vinculada à pasta <strong>{{PASTA_TITULO}}</strong>, "
            "vem reiterar integralmente os termos da inicial e das provas produzidas em audiência, requerendo a procedência das verbas "
            "trabalhistas, reflexos em FGTS + 40%, férias + 1/3, 13º salário e honorários sucumbenciais (art. 791-A da CLT).</p>"
            "<p><br></p>"
            "<p>{{DATA_EXTENSO}}</p>"
            "<p><strong>{{ADVOGADO_RESPONSAVEL}}</strong><br>{{ESCRITORIO_NOME}}</p>"
        ),
    },
}


class InterpoladorMinutasEngine:
    """Interpolador dinâmico de variáveis `{{CHAVE}}` a partir de uma Pasta Jurídica (`Matter`)."""

    MESES_PT = {
        1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
        5: "maio", 6: "junho", 7: "julho", 8: "agosto",
        9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
    }

    @classmethod
    def data_por_extenso(cls, d: date | None = None, cidade: str = "") -> str:
        hoje = d or timezone.localdate()
        mes = cls.MESES_PT.get(hoje.month, "")
        prefixo = f"{cidade}, " if cidade else ""
        return f"{prefixo}{hoje.day} de {mes} de {hoje.year}."

    @classmethod
    def extrair_variaveis_pasta(cls, matter, organization=None, user=None) -> dict[str, str]:
        client = getattr(matter, "client", None) if matter else None
        first_case = matter.court_cases.first() if matter else None

        endereco_partes = []
        if client:
            for attr in ("address", "district", "city", "state"):
                val = getattr(client, attr, "")
                if val:
                    endereco_partes.append(val)
        endereco_str = ", ".join(endereco_partes) if endereco_partes else "Endereço constante nos autos"
        cidade_cliente = getattr(client, "city", "") if client else ""

        advogado_nome = "Advogado(a) Responsável"
        if matter and getattr(matter, "owner", None):
            advogado_nome = matter.owner.get_full_name() or matter.owner.email
        elif user:
            advogado_nome = user.get_full_name() or user.email

        return {
            "NUMERO_PROCESSO": first_case.number if first_case else "0000000-00.2026.8.06.0001",
            "ORGAO_JULGADOR": (first_case.court if first_case and first_case.court else "Vara Cível / Juizado Especial"),
            "PARTE_CONTRARIA": (first_case.opposing_party if first_case and first_case.opposing_party else "Parte Adversa"),
            "NOME_CLIENTE": client.name if client else "Nome do Cliente",
            "CPF_CNPJ": (client.document if client and client.document else "000.000.000-00"),
            "ENDERECO_CLIENTE": endereco_str,
            "PASTA_TITULO": matter.title if matter else "Pasta Jurídica",
            "AREA_JURIDICA": (matter.area_label if matter and getattr(matter, "area", "") else "Direito Cível / Geral"),
            "ADVOGADO_RESPONSAVEL": advogado_nome,
            "ESCRITORIO_NOME": organization.name if organization else "Escritório de Advocacia",
            "DATA_EXTENSO": cls.data_por_extenso(timezone.localdate(), cidade=cidade_cliente),
        }

    @classmethod
    def interpolar(cls, template_html: str, variaveis: dict[str, str]) -> str:
        resultado = template_html or ""
        for chave, valor in variaveis.items():
            resultado = resultado.replace(f"{{{{{chave}}}}}", str(valor or ""))
        return resultado


class AssinaturaDigitalSha256:
    """
    Motor de Assinatura Eletrônica e Chancela de Integridade SHA-256
    (Portado de AssinaturaDigitalService.java — Padrão Lei 14.063/2020).
    """

    @staticmethod
    def assinar_conteudo(conteudo: str, signatario: str, organizacao_nome: str = "") -> dict[str, str]:
        agora = timezone.localtime(timezone.now())
        timestamp_str = agora.strftime("%d/%m/%Y %H:%M:%S")
        payload = f"{conteudo}|SIGNATARIO:{signatario}|ORG:{organizacao_nome}|TS:{agora.isoformat()}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()
        codigo_verificacao = f"JUMBI-{digest[:8]}-{digest[8:16]}-{digest[-8:]}"
        chancela_html = (
            f'<div style="margin-top:24px;padding:14px 18px;border:1px solid #d4af37;border-radius:10px;background:#faf8f2;font-size:12px;line-height:1.5;color:#1e293b;">'
            f'<strong>DOCUMENTO ASSINADO ELETRONICAMENTE — PADRÃO SHA-256 (LEI Nº 14.063/2020)</strong><br>'
            f'Signatário(a): <strong>{signatario}</strong> ({organizacao_nome})<br>'
            f'Data e Hora da Chancela: <strong>{timestamp_str}</strong><br>'
            f'Hash Criptográfico SHA-256: <code>{digest}</code><br>'
            f'Código de Autenticidade: <strong>{codigo_verificacao}</strong>'
            f'</div>'
        )
        return {
            "hash_sha256": digest,
            "codigo_verificacao": codigo_verificacao,
            "timestamp": timestamp_str,
            "signatario": signatario,
            "chancela_html": chancela_html,
            "conteudo_assinado": (conteudo or "") + chancela_html,
        }


class CorreicaoEngine:
    """
    Painel de Correição Interna e Auditoria de Conformidade do Acervo
    (Portado de CorreicaoController.java).
    """

    @classmethod
    def executar_correicao(cls, organization) -> dict[str, Any]:
        from apps.legal.models import Contact, CourtCase, Deadline, Matter, Task

        hoje = timezone.localdate()
        limite_48h = hoje + timedelta(days=2)

        # 1. Prazos vencidos e urgentes (48h)
        prazos_abertos = Deadline.objects.filter(
            organization=organization
        ).exclude(status=Deadline.Status.FULFILLED).select_related("matter", "owner")

        prazos_vencidos = [p for p in prazos_abertos if p.due_date < hoje]
        prazos_48h = [p for p in prazos_abertos if hoje <= p.due_date <= limite_48h]
        prazos_sem_conferencia = [p for p in prazos_abertos if p.status == Deadline.Status.PENDING]

        # 2. Auditoria de Numeração CNJ em todos os Processos (CourtCase)
        processos = list(CourtCase.objects.filter(organization=organization).select_related("matter"))
        processos_invalidos = []
        processos_validos = []
        for proc in processos:
            info = CnjValidator.inspect(proc.number)
            if info["is_valid"]:
                processos_validos.append({"case": proc, "info": info})
            else:
                processos_invalidos.append({"case": proc, "info": info})

        # 3. Pastas sem movimentação / sem tarefas abertas nem prazos futuros
        pastas_ativas = list(
            Matter.objects.filter(organization=organization, status=Matter.Status.ACTIVE)
            .select_related("client", "owner")
        )
        pastas_Com_tarefa = set(
            Task.objects.filter(
                organization=organization,
                status__in=[Task.Status.TODO, Task.Status.DOING, Task.Status.IN_REVIEW, Task.Status.BLOCKED],
                matter__isnull=False,
            ).values_list("matter_id", flat=True)
        )
        pastas_com_prazo = set(p.matter_id for p in prazos_abertos)
        pastas_sem_impulso = [
            m for m in pastas_ativas
            if m.pk not in pastas_Com_tarefa and m.pk not in pastas_com_prazo
        ]

        # 4. Clientes com cadastro incompleto (sem CPF/CNPJ ou telefone)
        contatos = list(Contact.objects.filter(organization=organization, status=Contact.Status.ACTIVE))
        contatos_incompletos = [
            c for c in contatos
            if not (c.document or "").strip() or not (c.phone or "").strip()
        ]

        # Cálculo do Índice de Conformidade da Controladoria (0 a 100)
        penalidades = (
            len(prazos_vencidos) * 12
            + len(prazos_sem_conferencia) * 4
            + len(processos_invalidos) * 5
            + len(pastas_sem_impulso) * 3
            + len(contatos_incompletos) * 2
        )
        indice_conformidade = max(15, 100 - penalidades)

        return {
            "data_inspecao": timezone.localtime(timezone.now()),
            "indice_conformidade": indice_conformidade,
            "total_pastas_ativas": len(pastas_ativas),
            "total_processos": len(processos),
            "prazos_vencidos": prazos_vencidos,
            "prazos_48h": prazos_48h,
            "prazos_sem_conferencia": prazos_sem_conferencia,
            "processos_invalidos": processos_invalidos,
            "processos_validos": processos_validos,
            "pastas_sem_impulso": pastas_sem_impulso,
            "contatos_incompletos": contatos_incompletos,
        }
