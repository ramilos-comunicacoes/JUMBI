"""End-to-end portability of v5 records, with real private file bytes."""
import hashlib
import io
import json
import tempfile
import zipfile
from datetime import timedelta
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization, User
from apps.core.test_platform import TEST_SETTINGS
from apps.fees.models import FeeInstallment, FeePlan
from apps.fees.services import create_plan
from apps.legal.models import Document, Matter, Contact
from apps.legal.services import add_document_version, audit, record_payment, reverse_payment
from apps.legal.views import accessible_audit, scoped_queryset
from apps.portal.models import ClientAccess, DocumentReview, PortalMessage, Publication, ReviewDecision
from apps.portal.services import decide_review, grant_access, publish_version, request_review, revoke, send_message
from apps.routines.models import MatterChecklist, MatterComment, RoutineApplication, RoutineTemplate
from apps.routines.services import add_comment, apply_template, set_checklist_status
from apps.security.models import AccountSecurity, SecurityEvent
from apps.security.services import cipher


V5_MODELS = [RoutineTemplate, RoutineApplication, MatterChecklist, MatterComment,
             FeePlan, FeeInstallment, ClientAccess, DocumentReview, ReviewDecision,
             Publication, PortalMessage]
AUTH_SECRET = "v5-export-test-secret-not-for-production-0123456789ABCDEF0123456789"


@override_settings(**TEST_SETTINGS, SECRET_KEY=AUTH_SECRET)
class ReuseExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Exportação v5", slug="v5-export", business_type="office")
        cls.other_org = Organization.objects.create(name="Escritório externo", slug="v5-export-other", business_type="office")
        for role in ["owner", "manager", "operator", "viewer", "client"]:
            user = User.objects.create_user(email=f"export-v5-{role}@example.test", first_name=role.title(), password="V5-only-test-password-42")
            setattr(cls, role if role != "client" else "client_user", user)
            member = Membership.objects.create(organization=cls.org, user=user, role=role)
            if role == "client":
                cls.client_member = member
        cls.private_reviewer = User.objects.create_user(email="v5-private-reviewer@example.test", first_name="Revisora")
        Membership.objects.create(organization=cls.org, user=cls.private_reviewer, role="manager")
        cls.outsider = User.objects.create_user(email="v5-other-owner@example.test", first_name="Externo")
        cls.other_reviewer = User.objects.create_user(email="v5-other-reviewer@example.test", first_name="Revisora externa")
        cls.other_client_user = User.objects.create_user(email="v5-other-client@example.test", first_name="Cliente externo")
        for user, role in [(cls.outsider, "owner"), (cls.other_reviewer, "manager"), (cls.other_client_user, "client")]:
            member = Membership.objects.create(organization=cls.other_org, user=user, role=role)
            if role == "client":
                cls.other_client_member = member
        cls.contact = Contact.objects.create(organization=cls.org, name="Cliente autorizado")
        cls.other_contact = Contact.objects.create(organization=cls.other_org, name="Cliente do outro escritório")
        cls.matter = Matter.objects.create(organization=cls.org, title="Pasta autorizada", client=cls.contact, owner=cls.owner)
        cls.secret = Matter.objects.create(organization=cls.org, title="SIGILO-V5 pasta", client=cls.contact, owner=cls.owner, confidential=True)
        cls.secret.members.add(cls.private_reviewer, cls.client_user)
        cls.other_matter = Matter.objects.create(organization=cls.other_org, title="EXTERNO-V5 pasta", client=cls.other_contact, owner=cls.outsider)
        cls.template = RoutineTemplate.objects.create(organization=cls.org, created_by=cls.owner, title="Rotina compartilhada", tasks=["Conferir documentos"], checklist=["Revisar os dados"], documents=["Documento de identidade"])
        cls.unused_archived_template = RoutineTemplate.objects.create(organization=cls.org, created_by=cls.owner, title="MODELO-ARQUIVADO-SEM-VINCULO", checklist=["Item de catálogo"], is_active=False)
        cls.application, _ = apply_template(actor=cls.owner, organization=cls.org, matter_id=cls.matter.pk, template_id=cls.template.pk, expected_version=1, task_due_date=timezone.localdate())
        cls.secret_application, _ = apply_template(actor=cls.owner, organization=cls.org, matter_id=cls.secret.pk, template_id=cls.template.pk, expected_version=1, task_due_date=timezone.localdate())
        cls.comment = add_comment(actor=cls.owner, matter=cls.matter, body="Comentário de equipe autorizado")
        cls.secret_comment = add_comment(actor=cls.owner, matter=cls.secret, body="SIGILO-V5 comentário")
        cls.check = cls.application.items.first()
        set_checklist_status(actor=cls.owner, item=cls.check, done=True, note="Dados conferidos", expected_version=1)
        cls.plan = create_plan(organization=cls.org, actor=cls.owner, matter=cls.matter, client=cls.contact, title="HONORARIO-V5 RESERVADO", kind="installments", amount="100.00", periods=3, first_due_date=timezone.localdate(), operation_key=uuid4())
        cls.secret_plan = create_plan(organization=cls.org, actor=cls.owner, matter=cls.secret, client=cls.contact, title="SIGILO-V5 honorários", kind="monthly", amount="200.00", periods=2, first_due_date=timezone.localdate(), operation_key=uuid4())
        cls.other_plan = create_plan(organization=cls.other_org, actor=cls.outsider, matter=cls.other_matter, client=cls.other_contact, title="EXTERNO-V5 honorários", kind="installments", amount="150.00", periods=2, first_due_date=timezone.localdate(), operation_key=uuid4())
        cls.payment = record_payment(entry=cls.plan.installments.first().entry, actor=cls.owner, amount="10.00", note="Adiantamento")
        cls.reversal = reverse_payment(payment=cls.payment, actor=cls.owner, note="Correção da baixa")
        cls.account = AccountSecurity.objects.create(user=cls.manager, enabled=False, secret_ciphertext=cipher().encrypt(b"MFA-V5-SEGREDO").decode(), recovery_hashes=["RECOVERY-V5-SEGREDO"])
        SecurityEvent.objects.create(user=cls.manager, action="ATIVIDADE-MFA-RESERVADA")

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = override_settings(PRIVATE_MEDIA_ROOT=directory.name)
        storage.enable()
        self.addCleanup(storage.disable)
        self.publication, self.version, self.review, self.decision, self.access = self.bundle(self.org, self.owner, self.manager, self.matter, self.client_member, self.contact, "AUTORIZADO-V5")
        self.secret_publication, self.secret_version, self.secret_review, _, _ = self.bundle(self.org, self.owner, self.private_reviewer, self.secret, self.client_member, self.contact, "SIGILO-V5")
        self.other_publication, _, _, _, _ = self.bundle(self.other_org, self.outsider, self.other_reviewer, self.other_matter, self.other_client_member, self.other_contact, "EXTERNO-V5")

    def bundle(self, organization, author, reviewer, matter, membership, contact, marker):
        document = Document.objects.create(organization=organization, matter=matter, title=f"{marker} documento", created_by=author)
        version = add_document_version(document=document, actor=author, file=SimpleUploadedFile("evidencia.txt", f"{marker} bytes preservados".encode()))
        review = request_review(actor=author, organization=organization, version=version, reviewer=reviewer, note=f"{marker} revisão interna")
        decision = decide_review(actor=reviewer, review=review, outcome="approved", note=f"{marker} justificativa interna")
        access = grant_access(actor=author, organization=organization, membership=membership, contact=contact)
        publication = publish_version(actor=author, review=review, access=access, title=f"{marker} publicação", note="Versão aprovada")
        send_message(actor=membership.user, publication=publication, body=f"{marker} mensagem")
        return publication, version, review, decision, access

    def export(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse("legal:export"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        self.addCleanup(archive.close)
        return json.loads(archive.read("records.json")), json.loads(archive.read("manifest.json")), archive

    def test_manager_export_preserves_all_authorized_chains_and_document_hashes(self):
        records, manifest, archive = self.export(self.manager)
        self.assertEqual([row["id"] for row in records["feeplan"]], [self.plan.pk])
        self.assertEqual([row["id"] for row in records["routineapplication"]], [self.application.pk])
        self.assertEqual([row["id"] for row in records["documentreview"]], [self.review.pk])
        self.assertEqual([row["id"] for row in records["publication"]], [self.publication.pk])
        self.assertEqual(records["documentreview"][0]["checksum"], self.version.checksum)
        self.assertEqual(records["feeplan"][0]["total_amount"], "100.00")
        references = {
            "routineapplication": {"matter_id": "matter", "template_id": "routinetemplate"},
            "matterchecklist": {"matter_id": "matter", "application_id": "routineapplication"},
            "mattercomment": {"matter_id": "matter"},
            "feeplan": {"matter_id": "matter", "client_id": "contact"},
            "feeinstallment": {"plan_id": "feeplan", "entry_id": "financeentry"},
            "payment": {"entry_id": "financeentry", "reversal_of_id": "payment"},
            "documentreview": {"version_id": "documentversion", "requested_by_id": "users", "reviewer_id": "users"},
            "reviewdecision": {"review_id": "documentreview", "actor_id": "users"},
            "publication": {"review_id": "documentreview", "access_id": "clientaccess", "published_by_id": "users"},
            "portalmessage": {"publication_id": "publication", "actor_id": "users"},
            "clientaccess": {"contact_id": "contact", "user_id": "users"},
        }
        for key, relations in references.items():
            for row in records[key]:
                for field, target in relations.items():
                    if row.get(field) is not None:
                        self.assertIn(row[field], {item["id"] for item in records[target]}, f"{key}.{field} must resolve to {target}")
        self.assertEqual(set(records["routineapplication"][0]["task_ids"]), {row["id"] for row in records["task"]})
        self.assertEqual(records["routineapplication"][0]["snapshot"], self.application.snapshot)
        self.assertTrue(any(row["completion_note"] == "Dados conferidos" for row in records["matterchecklist"]))
        for entry in manifest["files"]:
            payload = archive.read(entry["path"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])
            self.assertEqual(len(payload), entry["bytes"])
        for key, rows in records.items():
            self.assertEqual(manifest["counts"][key], len(rows))
        self.assertTrue(archive.read(records["documentversion"][0]["archive_path"]).startswith(b"AUTORIZADO-V5"))
        serialized = archive.read("records.json").decode()
        for marker in ["SIGILO-V5", "EXTERNO-V5", self.account.secret_ciphertext, "MFA-V5-SEGREDO", "RECOVERY-V5-SEGREDO", "ATIVIDADE-MFA-RESERVADA", AUTH_SECRET, self.manager.password]:
            self.assertNotIn(marker, serialized)
        self.assertNotIn("accountsecurity", records)
        self.assertNotIn("securityevent", records)
        self.assertNotIn("request_hash", records["feeplan"][0])
        self.assertNotIn("operation_key", records["feeplan"][0])
        self.assertTrue(all(set(row) == {"id", "display_name"} for row in records["users"]))

    def test_viewer_keeps_referenced_archived_routine_but_no_money_or_internal_portal(self):
        self.template.is_active = False
        self.template.save()
        records, manifest, archive = self.export(self.viewer)
        self.assertFalse(manifest["finance_included"])
        self.assertNotIn("financeentry", records)
        self.assertNotIn("payment", records)
        for key in ["feeplan", "feeinstallment", "clientaccess", "documentreview", "reviewdecision", "publication", "portalmessage"]:
            self.assertFalse(records.get(key))
        self.assertEqual([row["id"] for row in records["routinetemplate"]], [self.template.pk])
        self.assertEqual([row["id"] for row in records["routineapplication"]], [self.application.pk])
        self.assertEqual([row["id"] for row in records["mattercomment"]], [self.comment.pk])
        serialized = archive.read("records.json").decode()
        for marker in ["SIGILO-V5", "EXTERNO-V5", "HONORARIO-V5 RESERVADO", "revisão interna", "justificativa interna", "mensagem", "MODELO-ARQUIVADO-SEM-VINCULO"]:
            self.assertNotIn(marker, serialized)

    def test_operator_export_resolves_publication_recipient_without_granting_management(self):
        records, _, archive = self.export(self.operator)
        self.assertEqual([row["id"] for row in records["publication"]], [self.publication.pk])
        self.assertEqual([row["id"] for row in records["clientaccess"]], [self.access.pk])
        grants = {row["id"]: row for row in records["clientaccess"]}
        for publication in records["publication"]:
            self.assertIn(publication["access_id"], grants)
            self.assertIn(grants[publication["access_id"]]["user_id"], {row["id"] for row in records["users"]})
            self.assertIn(publication["review_id"], {row["id"] for row in records["documentreview"]})
        self.assertFalse(scoped_queryset(self.operator, self.org, ClientAccess).exists())
        self.assertFalse(records.get("feeplan"))
        self.assertNotIn("SIGILO-V5", archive.read("records.json").decode())

    def test_expiry_suspension_and_start_downgrade_keep_authorized_v5_history(self):
        with override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            subscription = OrganizationSubscription.objects.create(organization=self.org, plan="max", status="active")
            cases = [("max", "active", timezone.now() - timedelta(days=1)), ("start", "active", None), ("start", "suspended", None)]
            for plan, status, expires in cases:
                subscription.plan, subscription.status, subscription.expires_at = plan, status, expires
                subscription.save()
                with self.subTest(plan=plan, status=status, expired=expires is not None):
                    records, _, _ = self.export(self.manager)
                    self.assertEqual([row["id"] for row in records["feeplan"]], [self.plan.pk])
                    self.assertEqual(len(records["feeinstallment"]), 3)
                    self.assertEqual([row["id"] for row in records["publication"]], [self.publication.pk])
                    self.assertEqual([row["id"] for row in records["routineapplication"]], [self.application.pk])
                    self.assertTrue(any(row["object_type"] == "fees.feeplan" and row["object_id"] == str(self.plan.pk) for row in records["auditevent"]))

    def test_client_and_revoked_membership_cannot_export_or_use_internal_scopes(self):
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(reverse("legal:export")).status_code, 403)
        for user in [self.client_user, self.outsider]:
            for model in V5_MODELS:
                with self.subTest(user=user.pk, model=model.__name__):
                    self.assertFalse(scoped_queryset(user, self.org, model, for_export=True).exists())
            self.assertFalse(accessible_audit(user, self.org, for_export=True).exists())
        Membership.objects.filter(organization=self.org, user=self.manager).update(is_active=False)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("legal:export")).status_code, 403)
        for model in V5_MODELS:
            self.assertFalse(scoped_queryset(self.manager, self.org, model, for_export=True).exists())

    def test_revoked_publication_and_grant_remain_in_manager_history(self):
        revoke(actor=self.owner, record=self.publication, reason="Encerramento do compartilhamento")
        revoke(actor=self.owner, record=self.access, reason="Encerramento do vínculo")
        records, _, _ = self.export(self.manager)
        self.assertEqual(records["publication"][0]["revoke_reason"], "Encerramento do compartilhamento")
        self.assertEqual(records["clientaccess"][0]["revoke_reason"], "Encerramento do vínculo")
        self.assertIsNotNone(records["publication"][0]["revoked_at"])
        self.assertEqual(len(records["portalmessage"]), 1)
        ids = {row["id"] for row in records["users"]}
        self.assertIn(records["publication"][0]["revoked_by_id"], ids)

    def test_tampered_source_aborts_export_instead_of_sending_unverified_bytes(self):
        with self.version.file.storage.open(self.version.file.name, "wb") as stream:
            stream.write(b"bytes alterados")
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("legal:export")).status_code, 404)

    def test_audit_new_subjects_is_filtered_after_access_changes(self):
        audit(organization=self.org, actor=self.owner, action="routine.application_recorded", obj=self.application, description="Aplicação autorizada")
        audit(organization=self.org, actor=self.owner, action="routine.application_recorded", obj=self.secret_application, description="SIGILO-V5 evento")
        for model, obj in [(FeePlan, self.plan), (RoutineApplication, self.application), (DocumentReview, self.review), (ReviewDecision, self.decision), (Publication, self.publication)]:
            self.assertTrue(accessible_audit(self.manager, self.org, for_export=True).filter(object_type=model._meta.label_lower, object_id=str(obj.pk)).exists())
        self.assertFalse(accessible_audit(self.manager, self.org, for_export=True).filter(description__contains="SIGILO-V5").exists())
        self.matter.confidential = True
        self.matter.save()
        records, _, _ = self.export(self.manager)
        for key in ["routineapplication", "matterchecklist", "mattercomment", "feeplan", "feeinstallment", "documentreview", "reviewdecision", "publication", "portalmessage"]:
            self.assertFalse(records[key], key)
