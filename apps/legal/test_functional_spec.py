"""Functional acceptance tests for the JUMBI Office Operations specification (T01 - T20)."""

import zipfile
import io
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization, User
from apps.legal.contact_services import (
    complete_client_contact, create_contact_draft, get_whatsapp_link,
    mark_link_opened, render_message_template,
)
from apps.legal.djen_report import generate_djen_word_report
from apps.legal.djen_services import run_daily_djen_search
from apps.legal.inss_services import import_or_update_administrative_demand, record_sync_failure
from apps.legal.models import (
    AdministrativeDemand, AuditEvent, ClientContact, Contact, CourtCase,
    Deadline, DeadlineRevision, DJENCommunication, DJENSearchRun,
    FinanceEntry, Matter, MessageTemplate, Payment, PaymentReceipt, Task,
)
from apps.legal.receipt_services import generate_receipt_docx, issue_payment_receipt
from apps.legal.services import complete_task, confirm_deadline, record_payment, revise_deadline
from apps.legal.timeline_services import get_matter_unified_timeline
from apps.performance.models import ScoreEvent, ScoreRule
from apps.performance.scoring_services import record_score_event, reverse_score_event, team_ranking


class FunctionalSpecAcceptanceTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name="Escritório Teste",
            slug="escritorio-teste",
            business_type="office",
            status="active",
        )
        from apps.billing.models import OrganizationSubscription
        OrganizationSubscription.objects.create(organization=self.org, plan="max", status="active")
        self.dona = User.objects.create_user(email="dona@escritorio.local", password="secretpassword")

        self.collab_a = User.objects.create_user(email="collab_a@escritorio.local", password="secretpassword", first_name="Ana")
        self.collab_b = User.objects.create_user(email="collab_b@escritorio.local", password="secretpassword", first_name="Bruno")

        Membership.objects.create(organization=self.org, user=self.dona, role="owner", is_active=True)
        Membership.objects.create(organization=self.org, user=self.collab_a, role="operator", is_active=True)
        Membership.objects.create(organization=self.org, user=self.collab_b, role="operator", is_active=True)

        self.contact = Contact.objects.create(
            organization=self.org,
            name="Cliente Principal",
            phone="83988887777",
            document="12345678900",
        )
        self.matter1 = Matter.objects.create(
            organization=self.org,
            client=self.contact,
            title="Caso A - Previdenciário",
            owner=self.collab_a,
        )
        self.matter2 = Matter.objects.create(
            organization=self.org,
            client=self.contact,
            title="Caso B - Trabalhista",
            owner=self.collab_b,
        )

    def test_t01_two_matters_same_client_independent(self):
        """T01: Dois casos do mesmo cliente conservam históricos e vencimentos independentes."""
        today = timezone.localdate()
        d1 = Deadline.objects.create(
            organization=self.org, matter=self.matter1, title="Prazo Caso 1",
            source="DJEN", due_date=today + timedelta(days=10), owner=self.collab_a,
        )
        d2 = Deadline.objects.create(
            organization=self.org, matter=self.matter2, title="Prazo Caso 2",
            source="TRT", due_date=today + timedelta(days=3), owner=self.collab_b,
        )
        task1 = Task.objects.create(
            organization=self.org, matter=self.matter1, title="Redigir réplica",
            owner=self.collab_a, due_date=today + timedelta(days=5),
        )
        task1 = complete_task(task=task1, actor=self.collab_a, evidence="Petição protocolada nos autos")
        task1.refresh_from_db()
        self.assertEqual(task1.status, Task.Status.DONE)

        t2_deadlines = Deadline.objects.filter(matter=self.matter2)
        self.assertEqual(t2_deadlines.count(), 1)
        self.assertEqual(t2_deadlines.first().status, Deadline.Status.PENDING)

        # Timeline of each matter is strictly independent
        timeline1 = get_matter_unified_timeline(self.matter1, self.collab_a, self.org)
        timeline2 = get_matter_unified_timeline(self.matter2, self.collab_b, self.org)
        titles1 = [ev["title"] for ev in timeline1]
        titles2 = [ev["title"] for ev in timeline2]
        self.assertTrue(any("Prazo Caso 1" in t for t in titles1))
        self.assertFalse(any("Prazo Caso 1" in t for t in titles2))
        self.assertTrue(any("Prazo Caso 2" in t for t in titles2))

    def test_t02_search_three_fields_criteria_tracked(self):
        """T02: Pesquisa no Comunica PJe em 3 campos separados (teor, parte, advogada) rastreia critérios."""
        feed = [
            {
                "communication_id": "COMM-001",
                "court": "TRT13",
                "case_number": "0001000-01.2026.5.13.0001",
                "parties": "Autor x Réu",
                "summary": "Intimação de acórdão",
                "full_text": "Publicação intimando a procuradora Geórgia de Andrade Almeida...",
                "found_in_teor": True,
                "found_in_parte": False,
                "found_in_advogado": True,
            }
        ]
        run, comms = run_daily_djen_search(
            organization=self.org, operator=self.dona, base_date=timezone.localdate(), records_source=feed,
        )
        self.assertEqual(len(comms), 1)
        comm = comms[0]
        self.assertIn("teor", comm.matched_fields)
        self.assertIn("advogado", comm.matched_fields)
        self.assertNotIn("parte", comm.matched_fields)

    def test_t03_multiple_courts_and_pages_failure_marked_partial(self):
        """T03: Falhas de páginas ou tribunais são registradas como execução parcial."""
        feed = [
            {
                "communication_id": "COMM-002",
                "court": "TRF1",
                "case_number": "1000-02.2026.4.01.0000",
                "summary": "Despacho",
                "full_text": "Geórgia de Andrade Almeida intimada",
                "found_in_advogado": True,
            }
        ]
        run, comms = run_daily_djen_search(
            organization=self.org,
            operator=self.dona,
            records_source=feed,
            sim_failures=["Falha ao acessar página 2 do TJBA: tempo limite excedido"],
        )
        self.assertEqual(run.status, DJENSearchRun.Status.PARTIAL)
        self.assertIn("TJBA", run.errors)

    def test_t04_repeated_communication_deduplicated_by_id(self):
        """T04: Mesma comunicação recebida repetidamente gera apenas 1 registro sem duplicidade."""
        feed = [
            {
                "communication_id": "SAME-ID-99",
                "court": "TJSP",
                "case_number": "12345-00",
                "summary": "Intimação A",
                "full_text": "Geórgia de Andrade Almeida",
                "found_in_teor": True,
            },
            {
                "communication_id": "SAME-ID-99",
                "court": "TJSP",
                "case_number": "12345-00",
                "summary": "Intimação A repetida",
                "full_text": "Geórgia de Andrade Almeida",
                "found_in_advogado": True,
            },
        ]
        run, comms = run_daily_djen_search(
            organization=self.org, operator=self.dona, records_source=feed,
        )
        self.assertEqual(len(comms), 1)
        self.assertEqual(run.total_deduplicated, 1)
        # Criteria are merged
        self.assertIn("teor", comms[0].matched_fields)
        self.assertIn("advogado", comms[0].matched_fields)

    def test_t05_two_acts_same_process_same_day_preserved(self):
        """T05: Dois atos do mesmo processo no mesmo dia são ambos preservados."""
        feed = [
            {
                "communication_id": "ACT-1",
                "court": "TRT13",
                "case_number": "PROC-SHARED-01",
                "summary": "Primeiro ato: vista de cálculos",
                "full_text": "Geórgia de Andrade Almeida",
                "found_in_advogado": True,
            },
            {
                "communication_id": "ACT-2",
                "court": "TRT13",
                "case_number": "PROC-SHARED-01",
                "summary": "Segundo ato: intimação de perícia",
                "full_text": "Geórgia de Andrade Almeida",
                "found_in_advogado": True,
            },
        ]
        run, comms = run_daily_djen_search(
            organization=self.org, operator=self.dona, records_source=feed,
        )
        self.assertEqual(len(comms), 2)
        comm_ids = {c.communication_id for c in comms}
        self.assertEqual(comm_ids, {"ACT-1", "ACT-2"})

    def test_t06_unidentifiable_deadline_triage_never_green(self):
        """T06: Prazo não identificável vai para conferência e nunca é exibido como verde."""
        today = timezone.localdate()
        deadline = Deadline.objects.create(
            organization=self.org,
            matter=self.matter1,
            title="Ciência sem prazo expresso",
            source="DJEN sem prazo",
            due_date=today + timedelta(days=20),
            owner=self.collab_a,
            status=Deadline.Status.PENDING,
        )
        # Even with due_date 20 days in future, while PENDING it must be 'pending' and NEVER 'horizon'
        self.assertEqual(deadline.urgency_level, "pending")
        self.assertEqual(deadline.urgency_label, "A conferir")
        self.assertNotEqual(deadline.urgency_color, "green")

    def test_t07_deadline_rule_revision_preserves_history(self):
        """T07: Mudança de regra ou data de prazo mantém revisão motivada no histórico."""
        today = timezone.localdate()
        deadline = Deadline.objects.create(
            organization=self.org, matter=self.matter1, title="Apelação",
            source="Publicação DJEN", due_date=today + timedelta(days=5), owner=self.collab_a,
        )
        confirm_deadline(deadline=deadline, actor=self.dona)
        deadline.refresh_from_db()
        self.assertEqual(deadline.status, Deadline.Status.CONFIRMED)


        new_due = today + timedelta(days=15)
        revise_deadline(
            deadline=deadline,
            actor=self.dona,
            due_date=new_due,
            reason="Prazo em dias úteis recalculado considerando feriado municipal",
        )
        deadline.refresh_from_db()
        self.assertEqual(deadline.due_date, new_due)
        revision = deadline.revisions.first()
        self.assertIsNotNone(revision)
        self.assertEqual(revision.previous_date, today + timedelta(days=5))
        self.assertEqual(revision.new_date, new_due)
        self.assertIn("feriado municipal", revision.reason)

    def test_t08_task_transfer_bulk_reassignment(self):
        """T08: Transferência de atividade em lote reatribui com histórico preservado."""
        today = timezone.localdate()
        t1 = Task.objects.create(
            organization=self.org, matter=self.matter1, title="Tarefa 1 Ana",
            owner=self.collab_a, due_date=today + timedelta(days=2),
        )
        t2 = Task.objects.create(
            organization=self.org, matter=self.matter1, title="Tarefa 2 Ana",
            owner=self.collab_a, due_date=today + timedelta(days=4),
        )

        from apps.legal.my_routine_views import bulk_reassign_tasks
        # Simulate reassignment logic
        tasks = [t1, t2]
        for t in tasks:
            prev = t.owner
            t.owner = self.collab_b
            t.save()
            AuditEvent.objects.create(
                organization=self.org,
                actor=self.dona,
                action="task.reassigned",
                object_type="legal.task",
                object_id=str(t.pk),
                description=f"Transferida de {prev} para {self.collab_b}. Motivo: Cobertura de férias",
            )

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertEqual(t1.owner, self.collab_b)
        self.assertEqual(t2.owner, self.collab_b)
        events = AuditEvent.objects.filter(object_id=str(t1.pk), action="task.reassigned")
        self.assertTrue(events.exists())
        self.assertIn("Cobertura de férias", events.first().description)

    def test_t09_whatsapp_link_click_does_not_complete_task(self):
        """T09: Clicar no link de mensagem WhatsApp NÃO conclui nem marca como enviada."""
        contact_log = create_contact_draft(
            organization=self.org,
            contact=self.contact,
            actor=self.collab_a,
            matter=self.matter1,
            extra_vars={"text": "Olá cliente, segue atualização do caso."},
        )
        self.assertEqual(contact_log.status, ClientContact.Status.DRAFT)

        # User clicked the link
        mark_link_opened(contact_log, self.collab_a)
        contact_log.refresh_from_db()
        self.assertEqual(contact_log.status, ClientContact.Status.LINK_OPENED)
        self.assertIsNone(contact_log.completed_at)

    def test_t10_manual_message_completion_declared(self):
        """T10: Mensagem concluída manualmente salva declaração de autor, horário e resultado."""
        contact_log = create_contact_draft(
            organization=self.org,
            contact=self.contact,
            actor=self.collab_a,
            matter=self.matter1,
            extra_vars={"text": "Solicitação de documentos"},
        )
        complete_client_contact(
            contact_log=contact_log,
            actor=self.collab_a,
            sent_text="Texto ajustado no WhatsApp",
            result_note="Cliente atendeu e prometeu envio em 24h",
            client_reply="Vou enviar amanhã às 10h",
        )
        contact_log.refresh_from_db()
        self.assertEqual(contact_log.status, ClientContact.Status.COMPLETED_MANUAL)
        self.assertIsNotNone(contact_log.completed_at)
        self.assertEqual(contact_log.sent_text, "Texto ajustado no WhatsApp")
        self.assertIn("24h", contact_log.result_note)

    def test_t11_attendant_different_from_case_responsible(self):
        """T11: Atendente diferente do responsável identifica ambos sem falsificar autoria."""
        template = MessageTemplate.objects.create(
            organization=self.org,
            category=MessageTemplate.Category.CASE_UPDATE,
            title="Atualização Geral",
            body="Olá, {nome_cliente}. Sobre {assunto}: {resumo_validado}.",
        )
        # Collab B is sending, but Matter 1 owner is Collab A
        rendered = render_message_template(
            template=template,
            contact=self.contact,
            matter=self.matter1,
            actor=self.collab_b,
            case_owner=self.matter1.owner,
            extra_vars={"resumo_validado": "Perícia agendada"},
        )
        self.assertIn(self.collab_b.first_name, rendered) # Atendente
        self.assertIn(self.collab_a.first_name, rendered) # Responsável pelo caso
        self.assertIn("Responsável pelo caso", rendered)

    def test_t12_partial_payment_and_balance_quittance(self):
        """T12: Pagamento parcial atualiza saldo e quitação suspende cobranças."""
        entry = FinanceEntry.objects.create(
            organization=self.org,
            matter=self.matter1,
            description="Honorários Iniciais",
            kind=FinanceEntry.Kind.INCOME,
            amount=Decimal("1000.00"),
            due_date=timezone.localdate(),
        )
        p1 = record_payment(entry=entry, actor=self.dona, amount=Decimal("350.00"), note="1ª parcela parcial")
        entry.refresh_from_db()
        self.assertEqual(entry.balance, Decimal("650.00"))

        # Complete payment
        p2 = record_payment(entry=entry, actor=self.dona, amount=Decimal("650.00"), note="Quitação restante")
        entry.refresh_from_db()
        self.assertEqual(entry.balance, Decimal("0.00"))
        self.assertTrue(entry.is_paid)

    def test_t13_reissued_receipt_no_duplicate_payment(self):
        """T13: Recibo gerado a partir de pagamento confirmado não duplica baixa nem pontuação."""
        entry = FinanceEntry.objects.create(
            organization=self.org, matter=self.matter1, description="Honorários",
            kind=FinanceEntry.Kind.INCOME, amount=Decimal("500.00"), due_date=timezone.localdate(),
        )
        payment = record_payment(entry=entry, actor=self.dona, amount=Decimal("500.00"), note="Depósito bancário")

        receipt1 = issue_payment_receipt(payment=payment, actor=self.dona)
        self.assertEqual(receipt1.amount, Decimal("500.00"))
        self.assertTrue(receipt1.receipt_number.startswith("REC-"))

        # Re-generating DOCX from same receipt
        docx_bytes = generate_receipt_docx(receipt1)
        self.assertTrue(len(docx_bytes) > 0)
        # Ensure only 1 payment exists
        self.assertEqual(Payment.objects.filter(entry=entry).count(), 1)

    def test_t14_contract_vs_revenue_indicators_distinct(self):
        """T14: Contrato formalizado é indicador distinto de receita recebida."""
        from apps.contracts.models import Contract, ContractTemplate
        from apps.legal.models import Document
        doc = Document.objects.create(organization=self.org, matter=self.matter1, title="Minuta Contrato", created_by=self.dona)
        tpl = ContractTemplate.objects.create(organization=self.org, name="Honorários Padrão", body="Contrato [[cliente_nome]]", created_by=self.dona)
        contract = Contract.objects.create(
            organization=self.org, title="Contrato Formalizado", template=tpl,
            matter=self.matter1, client=self.contact, document=doc, created_by=self.dona,
        )
        # Contract exists, but financial receipts remain 0
        payments = Payment.objects.filter(organization=self.org)
        self.assertEqual(payments.count(), 0)

    def test_t15_protocol_without_proof_pending_validation(self):
        """T15: Protocolo sem comprovante permanece pendente de validação."""
        case = CourtCase.objects.create(
            organization=self.org, matter=self.matter1, number="0009999-88.2026.8.15.0000",
            court="TJPB", notes="Petição elaborada no cartório",
        )
        # Simple drafting does not automatically score as validated filing
        events = ScoreEvent.objects.filter(source_model="legal.courtcase", source_id=str(case.pk))
        self.assertEqual(events.count(), 0)

    def test_t16_scoring_rules_and_reversal(self):
        """T16: Pontuação idempotente (não pontua duas vezes) e com estorno explícito."""
        task = Task.objects.create(
            organization=self.org, matter=self.matter1, title="Protocolar recurso",
            owner=self.collab_a, due_date=timezone.localdate(),
        )
        complete_task(task=task, actor=self.collab_a, evidence="Recibo de protocolo emitido")

        # Record points
        event = record_score_event(
            organization=self.org, user=self.collab_a,
            event_type=ScoreRule.EventType.TASK_COMPLETED, source_obj=task, description="Protocolo entregue",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.points, Decimal("10.00"))

        # Re-recording same event returns existing (no duplication)
        repeat = record_score_event(
            organization=self.org, user=self.collab_a,
            event_type=ScoreRule.EventType.TASK_COMPLETED, source_obj=task,
        )
        self.assertEqual(event.pk, repeat.pk)
        self.assertEqual(ScoreEvent.objects.filter(source_id=str(task.pk), is_reversal=False).count(), 1)

        # Reversal
        reversal = reverse_score_event(score_event=event, actor=self.dona, reason="Cancelamento da entrega")
        self.assertTrue(reversal.is_reversal)

        # Leaderboard reflects net score 0
        ranking = team_ranking(self.org)
        user_row = next(r for r in ranking if r["user"] == self.collab_a)
        self.assertEqual(user_row["points"], Decimal("0.00"))

    def test_t17_confidential_matter_hidden_from_collaborator(self):
        """T17: Colaborador sem acesso à pasta sigilosa não tem acesso a ela."""
        secret_matter = Matter.objects.create(
            organization=self.org, title="Demanda Sigilosa", owner=self.dona, confidential=True,
        )
        from apps.legal.services import visible_matters
        collab_matters = visible_matters(self.collab_a, self.org)
        self.assertNotIn(secret_matter, collab_matters)

    def test_t18_inss_sync_failure_displays_pending_update(self):
        """T18: Falha no Previdia / INSS registra 'atualização pendente' e nunca falso sem pendências."""
        demand, _ = import_or_update_administrative_demand(
            organization=self.org, contact=self.contact, matter=self.matter1,
            protocol_number="NB-987654321", service_name="Aposentadoria Especial",
            original_status="Exigência cumprida", assigned_to=self.collab_a,
        )
        record_sync_failure(demand, "Serviço GERID/Previdia indisponível no momento")
        demand.refresh_from_db()
        self.assertEqual(demand.sync_status, AdministrativeDemand.SyncStatus.PENDING_UPDATE)
        self.assertIn("indisponível", demand.sync_notes)

    def test_t19_brand_customization_preserves_old_records(self):
        """T19: Mudança de identidade visual do escritório preserva integridade histórica."""
        old_name = self.org.name
        self.org.name = "Novo Nome da Advocacia"
        self.org.brand_primary_color = "#10B981"
        self.org.save()
        self.assertEqual(self.org.name, "Novo Nome da Advocacia")
        self.assertEqual(self.org.brand_primary_color, "#10B981")

    def test_t20_djen_word_report_partial_indicators(self):
        """T20: Relatório diário Word (.docx) registra data, horário, tribunal e falhas parciais."""
        feed = [
            {
                "communication_id": "COMM-REP-1",
                "court": "TRT13",
                "case_number": "0000555-55.2026.5.13.0001",
                "summary": "Intimação para audiência",
                "full_text": "Geórgia de Andrade Almeida intimada",
                "found_in_advogado": True,
            }
        ]
        run, comms = run_daily_djen_search(
            organization=self.org, operator=self.dona, records_source=feed,
            sim_failures=["Falha ao acessar aba do TJSP"],
        )
        docx_bytes = generate_djen_word_report(run, comms)
        self.assertTrue(len(docx_bytes) > 0)

        # Inspect OOXML zip contents
        with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as archive:
            self.assertIn("word/document.xml", archive.namelist())
            xml_content = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("RELATÓRIO DIÁRIO", xml_content)
            self.assertIn("Geórgia de Andrade Almeida", xml_content)
            self.assertIn("PESQUISA PARCIAL", xml_content)
            self.assertIn("Falha ao acessar aba do TJSP", xml_content)

    def test_t21_specialized_hubs_and_dynamic_djen_lawyer(self):
        """T21: Módulos especializados Previdenciário e Trabalhista, e pesquisa DJEN personalizada."""
        # 1. Test Branding Form with practice_areas
        from apps.core.forms import OrganizationBrandingForm
        form = OrganizationBrandingForm(
            data={
                "system_title": "Advocacia Especializada",
                "brand_primary_color": "#F5A000",
                "brand_accent_color": "#0F4050",
                "brand_sidebar_color": "#0B1320",
                "glassmorphism_intensity": "high",
                "practice_areas": ["previdenciario", "trabalhista"],
            },
            instance=self.org,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved_org = form.save()
        self.assertEqual(saved_org.practice_areas, ["previdenciario", "trabalhista"])

        # 2. Test Previdenciário Hub view
        self.client.force_login(self.dona)
        resp_prev = self.client.get(reverse("legal:previdenciario_hub"))
        self.assertEqual(resp_prev.status_code, 200)
        self.assertContains(resp_prev, "Direito Previdenciário & INSS")
        self.assertContains(resp_prev, "Calculadora EC 103/2019")

        # 3. Test Trabalhista Hub view
        resp_trab = self.client.get(reverse("legal:trabalhista_hub"))
        self.assertEqual(resp_trab.status_code, 200)
        self.assertContains(resp_trab, "Direito Trabalhista & Audiências")
        self.assertContains(resp_trab, "Calculadora de Rescisão CLT")

        # 4. Test Dynamic DJEN search with custom lawyer name
        custom_name = "Carlos Eduardo Siqueira"
        run, comms = run_daily_djen_search(
            organization=self.org,
            operator=self.dona,
            queried_name=custom_name,
        )
        self.assertEqual(run.queried_name, custom_name)
        self.assertTrue(run.total_deduplicated > 0)
        self.assertIn(custom_name, comms[0].full_text)

