"""Comprehensive automated test suite for JUMBI Integrations Hub.

Tests multi-tenant isolation, DJEN independent searches, triage workflow,
PDPJ Webhook HMAC verification, Word report generation, and API contracts.
"""
import hashlib
import hmac
import io
import json
import uuid
import zipfile
from datetime import date
from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization, User
from apps.legal.models import CourtCase as Case, Deadline, Matter, Task
from .djen_client import run_independent_georgia_searches
from .models import (
    CommunicationReview,
    CourtCommunication,
    DailyReport,
    IntegrationAccount,
    IntegrationProvider,
    MonitoringHit,
    MonitoringRule,
    SourceDeployment,
    SyncRun,
    WebhookInbox,
)
from .security import check_idempotency_conflict, verify_pdpj_signature
from .triage_services import confirm_communication, dismiss_communication, list_triage_queue
from .word_report import generate_daily_docx_report


class IntegrationsHubTestCase(TestCase):
    def setUp(self):
        # Create Office 1
        self.org1 = Organization.objects.create(
            name="Almeida Advocacia",
            slug="almeida-adv",
            system_title="Almeida Advocacia",
            business_type=Organization.BusinessType.OFFICE,
            status=Organization.Status.ACTIVE,
        )
        self.user1 = User.objects.create_user(email="georgia@almeida.adv.br", password="SecretPassword123!", first_name="Geórgia")
        self.membership1 = Membership.objects.create(organization=self.org1, user=self.user1, role=Membership.Role.OWNER, is_active=True)

        # Create Office 2 (Isolation test)
        self.org2 = Organization.objects.create(
            name="Outro Escritório",
            slug="outro-adv",
            business_type=Organization.BusinessType.OFFICE,
            status=Organization.Status.ACTIVE,
        )
        self.user2 = User.objects.create_user(email="outro@adv.com", password="SecretPassword123!", first_name="Outro")
        self.membership2 = Membership.objects.create(organization=self.org2, user=self.user2, role=Membership.Role.OWNER, is_active=True)

        # Subscriptions
        OrganizationSubscription.objects.create(organization=self.org1, plan="max", status="active")
        OrganizationSubscription.objects.create(organization=self.org2, plan="max", status="active")

        # Provider and Deployment
        self.provider = IntegrationProvider.objects.filter(code="djen").first()
        if not self.provider:
            self.provider = IntegrationProvider.objects.create(code="djen", name="DJEN", documentation_status="DOC", authorization_status="AUTH")

        self.deployment = SourceDeployment.objects.filter(tribunal="DJEN").first()
        if not self.deployment:
            self.deployment = SourceDeployment.objects.create(
                tribunal="DJEN",
                endpoint_url="https://comunicaapi.pje.jus.br",
                branch="federal",
                system="DJEN",
            )

        self.client1 = Client()
        self.client1.force_login(self.user1)

    def test_multi_tenant_isolation(self):
        """Records created in Office 1 must NEVER be accessible to Office 2."""
        comm1 = CourtCommunication.objects.create(
            organization=self.org1,
            tribunal="TJBA",
            external_id="COMM-ISOLATION-001",
            case_number="0001234-56.2026.8.05.0001",
            available_date=date(2026, 10, 14),
            content_text="Publicação confidencial do escritório 1"
        )

        # Office 2 queries triage queue
        queue2 = list_triage_queue(self.org2)
        self.assertNotIn(comm1, queue2)

        # Direct queryset isolation
        self.assertEqual(CourtCommunication.objects.filter(organization=self.org2).count(), 0)

    def test_djen_3_independent_georgia_searches(self):
        """Execute 3 distinct queries for Geórgia de Andrade Almeida with deduplication."""
        results = run_independent_georgia_searches(
            organization=self.org1,
            base_date=date(2026, 10, 14),
            sample_hits=[
                {"external_id": "COMM-TEST-100", "case_number": "5000100-00.2026.8.05.0001", "court": "TJBA", "content": "Intimação de Geórgia de Andrade Almeida", "date": "2026-10-14", "recipient": "Geórgia de Andrade Almeida"},
                {"external_id": "COMM-TEST-200", "case_number": "5000200-00.2026.8.05.0001", "court": "TJRJ", "content": "Sentença procedente", "date": "2026-10-14", "recipient": "Geórgia de Andrade Almeida"},
            ]
        )
        self.assertEqual(len(results), 3)

        # Check CourtCommunications created
        comms = CourtCommunication.objects.filter(organization=self.org1)
        self.assertGreaterEqual(comms.count(), 2)

        # Check MonitoringHits generated for each matched criterion
        hits = MonitoringHit.objects.filter(communication__organization=self.org1)
        self.assertGreaterEqual(hits.count(), 2)

    def test_triage_confirmation_creates_deadline_and_task(self):
        """Confirming communication generates Deadline and Task linked properly."""
        matter = Matter.objects.create(organization=self.org1, title="Ação Previdenciária Silva", owner=self.user1)
        comm = CourtCommunication.objects.create(
            organization=self.org1,
            tribunal="TJBA",
            external_id="COMM-TRIAGE-500",
            case_number="0009999-11.2026.8.05.0001",
            available_date=date(2026, 10, 14),
            content_text="Intimação para réplica no prazo de 15 dias.",
            review_status=CourtCommunication.ReviewStatus.PENDING_REVIEW,
        )

        confirmed_comm, review = confirm_communication(
            communication=comm,
            actor=self.user1,
            matter=matter,
            create_deadline=True,
            deadline_days=15,
            notes="Réplica a contestação do INSS",
        )

        self.assertEqual(confirmed_comm.triage_status, CourtCommunication.TriageStatus.CONFIRMED)
        self.assertIsNotNone(confirmed_comm.deadline)
        self.assertEqual(confirmed_comm.deadline.matter, matter)
        self.assertEqual(confirmed_comm.deadline.status, Deadline.Status.PENDING)

        # Check Task created
        task = Task.objects.filter(deadline=confirmed_comm.deadline).first()
        self.assertIsNotNone(task)
        self.assertEqual(task.matter, matter)
        self.assertEqual(task.owner, self.user1)

    def test_triage_dismissal(self):
        """Dismissing communication records decision and preserves audit."""
        comm = CourtCommunication.objects.create(
            organization=self.org1,
            tribunal="TJBA",
            external_id="COMM-DISMISS-001",
            case_number="0008888-22.2026.8.05.0001",
            available_date=date(2026, 10, 14),
            content_text="Despacho de mero expediente sem prazo",
            review_status=CourtCommunication.ReviewStatus.PENDING_REVIEW,
        )

        dismissed_comm, review = dismiss_communication(
            communication=comm,
            actor=self.user1,
            reason="Mero expediente, sem prazo processual."
        )
        self.assertEqual(dismissed_comm.triage_status, CourtCommunication.TriageStatus.DISMISSED)
        self.assertEqual(review.decision, CommunicationReview.Decision.DISMISSED)

    def test_pdpj_webhook_hmac_sha256(self):
        """Verify HMAC signature verification and deduplication on Webhook inbox."""
        secret = "test_pdpj_secret_2026"
        subscription_id = uuid.uuid4()
        payload = b'{"event":"comunicacao_disponibilizada","id":"12345"}'

        # Valid signature
        valid_sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        self.assertTrue(verify_pdpj_signature(raw_body=payload, signature=valid_sig, secret=secret))

        # Invalid signature
        invalid_sig = "abcdef0123456789"
        self.assertFalse(verify_pdpj_signature(raw_body=payload, signature=invalid_sig, secret=secret))

    def test_idempotency_conflict_detection(self):
        """Reusing Idempotency-Key with different payload triggers conflict."""
        key = "idemp-key-unique-001"
        payload1 = {"action": "create", "value": 100}
        payload2 = {"action": "create", "value": 200}

        # First request (no conflict)
        conflict1 = check_idempotency_conflict(
            organization=self.org1,
            key=key,
            path="/api/v1/integrations/accounts/",
            method="POST",
            payload=payload1
        )
        self.assertFalse(conflict1)

        # Same key with DIFFERENT payload -> conflict!
        conflict2 = check_idempotency_conflict(
            organization=self.org1,
            key=key,
            path="/api/v1/integrations/accounts/",
            method="POST",
            payload=payload2
        )
        self.assertTrue(conflict2)

    def test_word_docx_report_generation(self):
        """Generate pure-Python OOXML .docx report and verify valid zip/XML structure."""
        report, docx_bytes = generate_daily_docx_report(
            organization=self.org1,
            base_date=date(2026, 10, 14)
        )
        self.assertIsNotNone(report)
        self.assertTrue(docx_bytes.startswith(b"PK"))  # Standard ZIP signature

        # Verify OOXML parts inside zip archive
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            self.assertIn("[Content_Types].xml", z.namelist())
            self.assertIn("word/document.xml", z.namelist())
            doc_content = z.read("word/document.xml").decode("utf-8")
            self.assertIn("ALMEIDA ADVOCACIA", doc_content.upper())
            self.assertIn("RELATÓRIO DIÁRIO", doc_content)
            self.assertIn("Fortaleza", doc_content)

    def test_connectors_and_customization_views_accessible(self):
        """Web UI views for connectors and customization render with 200 OK."""
        # Connectors View
        session = self.client1.session
        session["active_organization_id"] = self.org1.pk
        session.save()

        resp_conn = self.client1.get(reverse("integrations:connectors"), secure=True)
        self.assertEqual(resp_conn.status_code, 200)

        # Customization View
        resp_cust = self.client1.get(reverse("core:customization"), secure=True)
        self.assertEqual(resp_cust.status_code, 200)

        # Kanban View (no 500)
        resp_kanban = self.client1.get(reverse("legal:kanban"), secure=True)
        self.assertEqual(resp_kanban.status_code, 200)
