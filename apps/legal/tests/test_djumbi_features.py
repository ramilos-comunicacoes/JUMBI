from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.models import Membership, Organization
from apps.legal.djumbi_engine import (
    AssinaturaDigitalSha256,
    CalculoPrazoEngine,
    CnjValidator,
    ContadoriaEngine,
    CorreicaoEngine,
    HeuristicIaClassifier,
    InterpoladorMinutasEngine,
    LitispendenciaEngine,
)
from apps.legal.models import Contact, CourtCase, Deadline, Document, Matter, Task


User = get_user_model()


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class DjumbiFeaturesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="advogado@jumbi.pro",
            password="StrongPassword123!",
            first_name="Dr. Advogado",
            last_name="Jumbi",
        )
        self.org = Organization.objects.create(
            name="Escritório Modelo DJUMBI",
            slug="escritorio-modelo-djumbi",
            business_type=Organization.BusinessType.OFFICE,
            status=Organization.Status.ACTIVE,
        )
        self.membership = Membership.objects.create(
            user=self.user,
            organization=self.org,
            role=Membership.Role.OWNER,
            is_active=True,
        )
        self.client_contact = Contact.objects.create(
            organization=self.org,
            name="Maria da Silva Oliveira",
            document="123.456.789-00",
            phone="(85) 99999-0000",
            address="Av. Santos Dumont, 1500",
            city="Fortaleza",
            state="CE",
        )
        self.matter = Matter.objects.create(
            organization=self.org,
            title="Ação Previdenciária — Maria da Silva",
            client=self.client_contact,
            nature=Matter.Nature.LITIGATION,
            area="previdenciario",
            owner=self.user,
        )
        # Compute a valid CNJ number dynamically using CnjValidator
        raw_base = "00012340020258060001"
        dd = CnjValidator.calculate_expected_dd(raw_base)
        self.valid_cnj = CnjValidator.format_cnj(f"0001234{dd}20258060001")
        self.court_case = CourtCase.objects.create(
            organization=self.org,
            matter=self.matter,
            number=self.valid_cnj,
            court="1ª Vara Cível de Fortaleza",
            opposing_party="INSS",
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_organization_id"] = self.org.pk
        session.save()

    def test_cnj_validator_modulo_97_and_tribunal_deduction(self):
        self.assertTrue(CnjValidator.is_valid(self.valid_cnj))
        info = CnjValidator.inspect(self.valid_cnj)
        self.assertTrue(info["is_valid"])
        self.assertEqual(info["tribunal"], "TJCE")
        self.assertEqual(info["year"], 2025)

        invalid_cnj = "0001234-00.2025.8.06.0001"
        if invalid_cnj == self.valid_cnj:
            invalid_cnj = "0001234-99.2025.8.06.0001"
        self.assertFalse(CnjValidator.is_valid(invalid_cnj))
        bad_info = CnjValidator.inspect(invalid_cnj)
        self.assertFalse(bad_info["is_valid"])
        self.assertIn("Módulo 97", bad_info["error"])

    def test_calculo_prazo_cpc_and_recesso_forense_art220(self):
        # Publicação em 18/12/2025 com 5 dias úteis atravessa o recesso forense (20/12 a 20/01)
        res = CalculoPrazoEngine.calcular(
            data_publicacao_ou_expedicao=date(2025, 12, 18),
            quantidade_dias=5,
            tipo_contagem="DIAS_UTEIS",
            suspender_recesso_cpc=True,
        )
        # 19/12/2025 é o 1º dia útil; 20/12 a 20/01 ficam suspensos; retoma em 21/01/2026
        self.assertGreaterEqual(res["data_fatal"], date(2026, 1, 26))
        self.assertTrue(any("Recesso Forense" in m["detalhe"] for m in res["memoria_calculo"]))

    def test_contadoria_selic_and_intercurrent_prescription(self):
        calc = ContadoriaEngine.calcular_debito(
            valor_original=Decimal("10000.00"),
            data_inicio=date(2025, 1, 1),
            data_fim=date(2026, 1, 1),
            indexador="SELIC",
            multa_percent=Decimal("10.0"),
            honorarios_percent=Decimal("10.0"),
        )
        self.assertEqual(calc["meses"], 12)
        self.assertEqual(calc["valor_juros"], Decimal("0.00"))
        self.assertGreater(calc["valor_total"], Decimal("12000.00"))

        presc = ContadoriaEngine.calcular_prescricao(
            modalidade="INTERCORRENTE_LEF_CPC",
            data_marco_inicial=date(2018, 1, 10),
            data_referencia=date(2026, 6, 1),
        )
        self.assertEqual(presc["fim_suspensao_anual"], date(2019, 1, 10))
        self.assertEqual(presc["termo_final_prescricao"], date(2024, 1, 10))
        self.assertTrue(presc["prescrito"])

    def test_ia_classifier_and_litispendencia_detector(self):
        ia = HeuristicIaClassifier.classificar_texto(
            "Intimação para manifestação sobre laudo pericial em ação de aposentadoria por incapacidade contra o INSS."
        )
        self.assertIn("Previdenciário", ia["categoria"])
        self.assertEqual(ia["prazo_sugerido_dias"], 15)

        alertas = LitispendenciaEngine.analisar_acervo(
            self.org,
            document="123.456.789-00",
            cnj_number=self.valid_cnj,
        )
        self.assertGreaterEqual(len(alertas), 1)
        self.assertEqual(alertas[0]["similaridade"], 100)

    def test_views_contadoria_pecas_sha256_and_correicao(self):
        # 1. GET Contadoria & Prazos
        resp = self.client.get(reverse("legal:contadoria_prazos"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Calculadora Determinística de Prazos Processuais")

        # 2. POST Agendar Prazo Fatal diretamente na Pasta + Criar Tarefa
        resp_post = self.client.post(
            reverse("legal:contadoria_prazos"),
            {
                "action": "agendar_prazo_pasta",
                "matter_id": self.matter.pk,
                "data_publicacao": "2026-03-02",
                "quantidade_dias": "15",
                "tipo_contagem": "DIAS_UTEIS",
                "titulo_prazo": "Contestação CPC 15d",
                "criar_tarefa_vinculada": "1",
            },
        )
        self.assertEqual(resp_post.status_code, 302)
        self.assertTrue(Deadline.objects.filter(matter=self.matter, title="Contestação CPC 15d").exists())
        self.assertTrue(Task.objects.filter(matter=self.matter, title__icontains="Contestação CPC 15d").exists())

        # 3. Export CSV da Contadoria
        resp_csv = self.client.get(reverse("legal:contadoria_prazos") + "?exportar_csv=1&valor_original=5000")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv["Content-Type"], "text/csv; charset=utf-8")

        # 4. Banco de Peças + Assinatura Digital SHA-256 + Arquivamento na Pasta
        resp_pecas = self.client.post(
            reverse("legal:pecas_minutas"),
            {
                "action": "assinar_salvar",
                "matter_id": self.matter.pk,
                "modelo_key": "peticao_previdenciaria_inss",
                "titulo_peca": "Petição Inicial Previdenciária Assinada",
                "conteudo_html": "<p>Petição de Maria da Silva Oliveira</p>",
                "arquivar_na_pasta": "1",
            },
        )
        self.assertEqual(resp_pecas.status_code, 200)
        self.assertContains(resp_pecas, "JUMBI-")
        doc = Document.objects.filter(matter=self.matter, title="Petição Inicial Previdenciária Assinada").first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.versions.count(), 1)

        # 5. Painel de Correição & IA
        resp_corr = self.client.get(reverse("legal:correicao_ia"))
        self.assertEqual(resp_corr.status_code, 200)
        self.assertContains(resp_corr, "Score de Conformidade")
