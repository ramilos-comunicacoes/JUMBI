import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from apps.core.models import Membership, Organization, User
from apps.billing.models import OrganizationSubscription
from apps.legal.models import Contact, Matter, ClientContact, Task, FinanceEntry, AdministrativeDemand, Deadline
from apps.legal.timeline_services import get_matter_unified_timeline
from apps.legal.inss_services import import_or_update_administrative_demand
from .models import IntegrationProvider, IntegrationAccount, CourtCommunication, SyncRun, WebhookInbox, ApiRequest
from .credentials import encrypt_credentials, decrypt_credentials
from .djen_client import run_independent_searches, extract_proposed_deadline
from .triage_services import confirm_communication


class ProductionAuditTests(TestCase):
    def test_suspended_or_expired_subscription_cannot_use_integration_ui_or_api(self):
        subscription = OrganizationSubscription.objects.get(organization=self.org)
        for changes in [{"status": "suspended"}, {"status": "active", "expires_at": timezone.now() - timedelta(days=1)}]:
            OrganizationSubscription.objects.filter(pk=subscription.pk).update(**changes)
            for route in ["integrations:connectors", "integrations:triage", "integrations:api_accounts", "integrations:api_communications"]:
                with self.subTest(changes=changes, route=route):
                    response = self.client.get(reverse(route))
                    self.assertEqual(response.status_code, 403)
            response = self.command("integrations:api_accounts", {"provider_code": "djen", "label": "Acesso suspenso"}, key="suspended")
            self.assertEqual(response.status_code, 403)
            self.assertFalse(IntegrationAccount.objects.filter(label="Acesso suspenso").exists())

    def setUp(self):
        self.org = Organization.objects.create(name="Audit", slug="audit", business_type="office")
        self.user = User.objects.create_user(email="manager@example.test", password="ExampleTest123!")
        self.hidden_owner = User.objects.create_user(email="private@example.test", password="ExampleTest123!")
        self.member = Membership.objects.create(organization=self.org, user=self.user, role="owner")
        Membership.objects.create(organization=self.org, user=self.hidden_owner, role="operator")
        OrganizationSubscription.objects.create(organization=self.org, plan="max", status="active")
        self.contact = Contact.objects.create(organization=self.org, name="Cliente")
        self.matter = Matter.objects.create(organization=self.org, title="Pasta aberta", client=self.contact, owner=self.user)
        self.hidden = Matter.objects.create(organization=self.org, title="Segredo reservado", client=self.contact, owner=self.hidden_owner, confidential=True)
        self.client.force_login(self.user)
        self.provider, _ = IntegrationProvider.objects.get_or_create(code="djen", defaults={"name":"DJEN"})

    def command(self, route, data, key="audit-1", args=None, method="post"):
        return getattr(self.client, method)(reverse(route, args=args), json.dumps(data), content_type="application/json", HTTP_IDEMPOTENCY_KEY=key)

    def test_api_credentials_encrypted_idempotent_and_never_returned(self):
        body = {"provider_code":"djen", "label":"Teste", "credentials":{"api_key":"sensitive-example-value"}}
        first = self.command("integrations:api_accounts", body)
        self.assertEqual(first.status_code, 201, first.content)
        replay = self.command("integrations:api_accounts", body)
        self.assertEqual(first.json(), replay.json())
        account = IntegrationAccount.objects.get(pk=first.json()["id"])
        self.assertNotIn("sensitive-example-value", account.encrypted_credentials)
        self.assertEqual(decrypt_credentials(account.encrypted_credentials), body["credentials"])
        self.assertNotContains(self.client.get(reverse("integrations:api_accounts")), "sensitive-example-value")
        self.assertEqual(self.command("integrations:api_accounts", dict(body, label="Outro")).status_code, 409)
        self.assertEqual(IntegrationAccount.objects.filter(label="Teste").count(), 1)

    def test_api_invalid_json_and_missing_account_are_handled(self):
        self.assertEqual(self.command("integrations:api_accounts", [], key="invalid").status_code, 400)
        response = self.command("integrations:api_monitors", {"account_id":str(uuid.uuid4()), "label":"X", "kind":"lawyer_name", "value":"Pessoa"}, key="none")
        self.assertEqual(response.status_code, 404)

    def test_client_and_viewer_cannot_read_integrations(self):
        for role in ["viewer", "operator", "client"]:
            self.member.role=role; self.member.save()
            response=self.client.get(reverse("integrations:api_accounts"))
            self.assertIn(response.status_code, [302,403])
            self.assertNotEqual(self.client.get(reverse("integrations:connectors")).status_code,200)

    def test_confidential_messages_and_assignments_are_not_exposed(self):
        msg=ClientContact.objects.create(organization=self.org, contact=self.contact, matter=self.hidden, actor=self.hidden_owner, case_owner=self.hidden_owner, phone="5588999999999", prepared_text="Mensagem sigilosa")
        self.assertNotContains(self.client.get(reverse("legal:contact_messages_list")), "Mensagem sigilosa")
        self.assertEqual(self.client.get(reverse("legal:contact_message_detail", args=[msg.pk])).status_code,404)
        task=Task.objects.create(organization=self.org,matter=self.hidden,title="Segredo reservado",owner=self.hidden_owner,due_date=timezone.localdate())
        self.client.post(reverse("legal:bulk_reassign_tasks"), {"task_ids":[task.pk],"new_owner":self.user.pk,"reason":"teste"})
        task.refresh_from_db();self.assertEqual(task.owner,self.hidden_owner)

    def test_revoked_matter_disappears_from_personal_routine(self):
        self.hidden.members.add(self.user)
        task=Task.objects.create(organization=self.org,matter=self.hidden,title="Tarefa antes autorizada",owner=self.user,due_date=timezone.localdate())
        self.hidden.members.remove(self.user)
        page=self.client.get(reverse("legal:my_routine"))
        self.assertNotContains(page, "Tarefa antes autorizada")

    def test_timeline_hides_financial_values_from_operator(self):
        self.member.role="operator";self.member.save()
        FinanceEntry.objects.create(organization=self.org,matter=self.matter,description="Financeiro secreto",amount="999.99",kind="income",due_date=timezone.localdate())
        events=get_matter_unified_timeline(self.matter,self.user,self.org)
        self.assertFalse(any(e["type"]=="financial_event" for e in events))

    def test_inss_rejected_status_and_missing_due_date(self):
        demand,_=import_or_update_administrative_demand(organization=self.org,contact=self.contact,matter=self.matter,protocol_number="123",service_name="Benefício",original_status="Indeferido",assigned_to=self.user)
        self.assertEqual(demand.status,AdministrativeDemand.Status.REJECTED)
        demand.status=AdministrativeDemand.Status.REQUIREMENT;demand.save()
        page=self.client.get(reverse("legal:previdenciario_hub"))
        self.assertContains(page,"Vencimento a conferir")
        self.assertIsNone(page.context["demands_with_deadlines"][0]["deadline_date"])

    def test_triage_requires_real_due_date_and_cannot_duplicate(self):
        comm=CourtCommunication.objects.create(organization=self.org,external_id="test-1",content_text="Texto da publicação")
        with self.assertRaises(ValidationError):
            confirm_communication(communication=comm,actor=self.user,matter=self.matter,notes="Fonte conferida")
        due=timezone.localdate()+timedelta(days=8)
        result,_=confirm_communication(communication=comm,actor=self.user,matter=self.matter,due_date=due,notes="Fonte conferida")
        self.assertEqual(result.deadline.due_date,due)
        self.assertEqual(result.deadline.status,Deadline.Status.PENDING)
        with self.assertRaises(ValidationError):
            confirm_communication(communication=comm,actor=self.user,matter=self.matter,due_date=due,notes="Fonte conferida")
        self.assertEqual(Deadline.objects.count(),1)

    def test_djen_failure_never_invents_results_and_preserves_reviews(self):
        with patch("apps.integrations.djen_client.DJENClient.search_communications", return_value={"success":False,"error":"Unavailable"}):
            result=run_independent_searches(organization=self.org,operator=self.user,target_name="Nome de teste")
        self.assertEqual(result.status,SyncRun.Status.FAILED)
        self.assertEqual(result.item_count,0)
        self.assertEqual(CourtCommunication.objects.count(),0)
        feed=[{"external_id":"official-1","content":"Nome de teste", "recipient":"Nome de teste"}]
        run_independent_searches(organization=self.org,operator=self.user,target_name="Nome de teste",mock_feed=feed)
        comm=CourtCommunication.objects.get(external_id="official-1")
        comm.review_status=CourtCommunication.ReviewStatus.NOT_RELEVANT;comm.save()
        run_independent_searches(organization=self.org,operator=self.user,target_name="Nome de teste",mock_feed=feed)
        comm.refresh_from_db();self.assertEqual(comm.review_status,CourtCommunication.ReviewStatus.NOT_RELEVANT)
        self.assertIsNone(extract_proposed_deadline("prazo de 15 dias",timezone.localdate())[0])

    def test_full_pages_marked_partial(self):
        items=[{"id":f"item-{i}","texto":"Publicação"} for i in range(20)]
        with patch("apps.integrations.djen_client.DJENClient.search_communications", return_value={"success":True,"data":{"items":items},"raw_bytes":b"{}","sha256":"a"*64}):
            result=run_independent_searches(organization=self.org,operator=self.user,target_name="Nome de teste")
        self.assertEqual(result.status,SyncRun.Status.PARTIAL)
        self.assertTrue(any(x["code"]=="PAGE_BUDGET" for x in result.sync_run.errors))

    def test_webhook_has_no_default_secret_and_is_tenant_bound(self):
        self.assertEqual(self.client.post(reverse("integrations:api_pdpj_webhook",args=[uuid.uuid4()]),b'{}',content_type="application/json").status_code,503)
        provider,_=IntegrationProvider.objects.get_or_create(code="pdpj-webhook",defaults={"name":"Webhook"})
        secret="test-webhook-specific-secret"
        account=IntegrationAccount.objects.create(organization=self.org,provider=provider,label="Webhook",encrypted_credentials=encrypt_credentials({"webhook_secret":secret}),has_credentials=True)
        body=b'{"id":"event-1","kind":"communication"}'
        signature=hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()
        url=reverse("integrations:api_pdpj_webhook",args=[account.pk])
        response=self.client.post(url,body,content_type="application/json",HTTP_X_PDPJ_WEBHOOK_SIGNATURE=signature)
        self.assertEqual(response.status_code,202,response.content)
        self.assertEqual(WebhookInbox.objects.get().organization,self.org)
        replay=self.client.post(url,body,content_type="application/json",HTTP_X_PDPJ_WEBHOOK_SIGNATURE=signature)
        self.assertTrue(replay.json()["duplicate"])
        self.assertEqual(WebhookInbox.objects.count(),1)
