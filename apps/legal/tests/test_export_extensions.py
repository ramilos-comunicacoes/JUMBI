import hashlib
import io
import json
import tempfile
import zipfile
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.contracts.models import Contract, ContractRevision, ContractTemplate
from apps.contracts.services import generate_revision
from apps.core.models import Membership, Organization, User
from apps.core.test_platform import TEST_SETTINGS
from apps.legal.models import Contact, Matter
from apps.legal.services import audit
from apps.legal.views import accessible_audit, scoped_queryset
from apps.performance.models import Goal, GoalUpdate
from apps.performance.services import record_progress, save_goal


@override_settings(**TEST_SETTINGS)
class ExtendedAuditExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Exportação", slug="extended-export", business_type="office", practice_areas=["civil", "familia", "trabalhista"])
        cls.other_org = Organization.objects.create(name="Outro", slug="extended-other", business_type="office")
        cls.owner = User.objects.create_user("owner@extended.test", "OnlyForTests!758")
        cls.manager = User.objects.create_user("manager@extended.test", "OnlyForTests!759")
        cls.viewer = User.objects.create_user("viewer@extended.test", "OnlyForTests!760")
        cls.outsider = User.objects.create_user("outsider@extended.test", "OnlyForTests!761")
        for user, role in [(cls.owner, "owner"), (cls.manager, "manager"), (cls.viewer, "viewer")]:
            Membership.objects.create(organization=cls.org, user=user, role=role)
        Membership.objects.create(organization=cls.other_org, user=cls.outsider, role="owner")
        cls.contact = Contact.objects.create(organization=cls.org, name="Cliente autorizado", birth_date=timezone.localdate() - timedelta(days=7300))
        cls.matter = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Pasta visível", area="civil")
        cls.secret = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="SEGREDO DA PASTA", confidential=True)
        cls.template = ContractTemplate.objects.create(organization=cls.org, created_by=cls.owner, name="Modelo compartilhado", body="Contrato: [[cliente_nome]]")
        cls.archived_template = ContractTemplate.objects.create(organization=cls.org, created_by=cls.owner, name="Modelo arquivado sem contrato", body="Arquivo interno da biblioteca", is_active=False)
        cls.other_template = ContractTemplate.objects.create(organization=cls.other_org, created_by=cls.outsider, name="EXTERNO MODELO", body="Externo")
        today = timezone.localdate()
        data = {"title": "Meta manual autorizada", "description": "Atendimentos", "metric": "manual", "target": Decimal("10"), "starts_on": today, "ends_on": today + timedelta(days=30), "owner": None, "niche": "civil", "archived": False}
        cls.goal = save_goal(actor=cls.owner, organization=cls.org, data=data)
        record_progress(actor=cls.owner, organization=cls.org, goal_id=cls.goal.pk, value="4", note="Evidência de atendimentos")
        cls.finance_goal = save_goal(actor=cls.owner, organization=cls.org, data={**data, "title": "RESERVADO FINANCEIRO", "metric": "revenue", "target": Decimal("5000")})
        cls.other_goal = save_goal(actor=cls.outsider, organization=cls.other_org, data={**data, "title": "EXTERNO META", "niche": ""})

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_MEDIA_ROOT=directory.name)
        storage.enable()
        self.addCleanup(storage.disable)
        self.revision = generate_revision(actor=self.owner, organization=self.org, template=self.template, matter=self.matter, client=self.contact, title="Contrato permitido", source_body=self.template.body, values={"cliente_nome": "Cliente autorizado"})
        self.secret_revision = generate_revision(actor=self.owner, organization=self.org, template=self.template, matter=self.secret, client=self.contact, title="SEGREDO CONTRATO", source_body=self.template.body, values={"cliente_nome": "SEGREDO TEXTO"})
        audit(organization=self.org, actor=self.owner, action="contract.template_updated", obj=self.template, description="Modelo compartilhado atualizado")
        audit(organization=self.org, actor=self.owner, action="contract.template_archived", obj=self.archived_template, description="Modelo arquivado sem vínculo")
        self.client.force_login(self.manager)

    def export(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse("legal:export"))
        self.assertEqual(response.status_code, 200)
        payload = b"".join(response.streaming_content)
        archive = zipfile.ZipFile(io.BytesIO(payload))
        self.addCleanup(archive.close)
        return json.loads(archive.read("records.json")), json.loads(archive.read("manifest.json")), archive

    def test_export_preserves_contract_revision_bytes_goal_history_and_niches(self):
        records, manifest, archive = self.export(self.manager)
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["organization"]["practice_areas"], self.org.practice_areas)
        self.assertEqual([row["id"] for row in records["contract"]], [self.revision.contract_id])
        self.assertEqual([row["id"] for row in records["contractrevision"]], [self.revision.pk])
        exported = records["contractrevision"][0]
        self.assertEqual(exported["values"], self.revision.values)
        self.assertEqual(exported["checksum"], self.revision.checksum)
        self.assertEqual(exported["operation_key"], str(self.revision.operation_key))
        self.assertEqual(len(records["documentversion"]), 1)
        self.assertEqual(exported["document_version_id"], records["documentversion"][0]["id"])
        self.assertTrue(archive.read(records["documentversion"][0]["archive_path"]).startswith(b"PK"))
        self.assertEqual(records["goalupdate"][0]["note"], "Evidência de atendimentos")
        self.assertEqual({row["id"] for row in records["goal"]}, {self.goal.pk, self.finance_goal.pk})
        content = archive.read("records.json").decode()
        self.assertNotIn("SEGREDO", content)
        self.assertNotIn("EXTERNO", content)
        self.assertNotIn("password", content)
        for item in manifest["files"]:
            self.assertEqual(hashlib.sha256(archive.read(item["path"])).hexdigest(), item["sha256"])

    def test_viewer_export_excludes_financial_goals_and_confidential_audit(self):
        # Archived templates needed by allowed contracts keep the references reconstructible.
        self.template.is_active = False
        self.template.save()
        records, manifest, archive = self.export(self.viewer)
        self.assertFalse(manifest["finance_included"])
        self.assertNotIn("financeentry", records)
        self.assertEqual([row["id"] for row in records["goal"]], [self.goal.pk])
        self.assertEqual([row["id"] for row in records["contracttemplate"]], [self.template.pk])
        self.assertEqual([row["id"] for row in records["contractrevision"]], [self.revision.pk])
        content = archive.read("records.json").decode()
        self.assertNotIn("RESERVADO FINANCEIRO", content)
        self.assertNotIn("SEGREDO", content)
        self.assertNotIn("Modelo arquivado sem vínculo", content)

    def test_expired_or_downgraded_plan_keeps_role_authorized_portability(self):
        with override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            subscription = OrganizationSubscription.objects.create(organization=self.org, plan="max", status="active", expires_at=timezone.now() - timedelta(days=1))
            self.assertFalse(accessible_audit(self.manager, self.org).filter(object_type="performance.goal", object_id=str(self.finance_goal.pk)).exists())
            for plan, status in [("max", "active"), ("start", "active"), ("start", "suspended")]:
                subscription.plan, subscription.status = plan, status
                subscription.save()
                records, manifest, archive = self.export(self.manager)
                self.assertIn(self.finance_goal.pk, [row["id"] for row in records["goal"]])
                self.assertTrue(any(row["object_type"] == "performance.goal" and row["object_id"] == str(self.finance_goal.pk) for row in records["auditevent"]))
                self.assertEqual(len(records["contractrevision"]), 1)

    def test_audit_includes_visible_new_subjects_but_never_cross_tenant_or_secret(self):
        events = accessible_audit(self.manager, self.org)
        self.assertTrue(events.filter(object_type="contracts.contractrevision", object_id=str(self.revision.pk)).exists())
        self.assertFalse(events.filter(object_type="contracts.contractrevision", object_id=str(self.secret_revision.pk)).exists())
        self.assertTrue(events.filter(object_type="performance.goal", object_id=str(self.goal.pk), action="goal.progress").exists())
        self.assertFalse(accessible_audit(self.viewer, self.org).filter(object_type="performance.goal", object_id=str(self.finance_goal.pk)).exists())
        for model in [Contract, ContractRevision, ContractTemplate, Goal, GoalUpdate]:
            with self.subTest(model=model.__name__):
                self.assertFalse(scoped_queryset(self.outsider, self.org, model, for_export=True).exists())
        self.assertFalse(accessible_audit(self.outsider, self.org, for_export=True).exists())
