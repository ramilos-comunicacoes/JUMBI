import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.legal.models import Contact, Document, DocumentVersion, Matter
from apps.legal.services import add_document_version
from .models import ClientAccess, DocumentReview, PortalMessage, Publication, ReviewDecision
from .services import (decide_review, grant_access, publish_version, request_review, revoke,
                       scoped_portal_queryset, send_message, verified_source, visible_publications)


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class PortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Portal fictício", slug="portal-test", business_type="office")
        cls.other = Organization.objects.create(name="Outro portal", slug="portal-other", business_type="office")
        for name, role, org in [("owner", "owner", cls.org), ("reviewer", "manager", cls.org), ("operator", "operator", cls.org), ("viewer", "viewer", cls.org), ("client_user", "client", cls.org), ("second_client", "client", cls.org), ("outsider", "owner", cls.other)]:
            user = get_user_model().objects.create_user(email=f"{name}@portal.example.test", password="portal-test-passphrase")
            setattr(cls, name, user)
            member = Membership.objects.create(organization=org, user=user, role=role)
            setattr(cls, name + "_membership", member)
        cls.contact = Contact.objects.create(organization=cls.org, name="Cliente fictício")
        cls.other_contact = Contact.objects.create(organization=cls.other, name="Contato externo")
        cls.matter = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Pasta interna confidencial em contexto")
        cls.secret = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Segredo", confidential=True)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.override = override_settings(PRIVATE_MEDIA_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.override.disable)
        self.client.force_login(self.owner)
        self.doc = Document.objects.create(organization=self.org, matter=self.matter, title="Documento interno", created_by=self.owner)
        self.version = add_document_version(document=self.doc, actor=self.owner, file=SimpleUploadedFile("versao1.txt", b"Exact immutable bytes"))

    def review(self, **kwargs):
        params = dict(actor=self.owner, organization=self.org, version=self.version, reviewer=self.reviewer, note="Conferir dados e clausulas.")
        params.update(kwargs)
        return request_review(**params)

    def approved(self, **kwargs):
        review = self.review(**kwargs)
        decide_review(actor=self.reviewer, review=review, outcome="approved", note="Dados conferidos.")
        return review

    def access(self, **kwargs):
        params = dict(actor=self.owner, organization=self.org, membership=self.client_user_membership, contact=self.contact)
        params.update(kwargs)
        return grant_access(**params)

    def publication(self, **kwargs):
        params = dict(actor=self.owner, review=self.approved(), access=self.access(), title="Contrato aprovado", note="Confira os dados finais.")
        params.update(kwargs)
        return publish_version(**params)

    def test_explicit_grant_does_not_release_documents(self):
        self.access()
        self.assertFalse(visible_publications(self.client_user, self.org).exists())
        self.client.force_login(self.client_user)
        self.assertContains(self.client.get(reverse("portal:home")), "Seu espaço está pronto")

    def test_independent_approval_exact_version_and_client_download(self):
        publication = self.publication()
        self.client.force_login(self.client_user)
        detail = self.client.get(reverse("portal:publication", args=[publication.pk]))
        self.assertContains(detail, "Contrato aprovado")
        self.assertNotContains(detail, self.matter.title)
        self.assertNotContains(detail, self.owner.email)
        response = self.client.get(reverse("portal:download", args=[publication.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"Exact immutable bytes")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertIn("attachment", response["Content-Disposition"])

    def test_new_version_does_not_replace_published_bytes(self):
        publication = self.publication()
        add_document_version(document=self.doc, actor=self.owner, file=SimpleUploadedFile("new.txt", b"Not approved bytes"))
        publication.refresh_from_db()
        self.assertEqual(publication.review.version_id, self.version.pk)
        self.client.force_login(self.client_user)
        response = self.client.get(reverse("portal:download", args=[publication.pk]))
        self.assertEqual(b"".join(response.streaming_content), b"Exact immutable bytes")
        self.assertEqual(self.client.get(reverse("legal:document_download", args=[self.doc.latest_version.pk])).status_code, 403)

    def test_self_approval_and_uploader_approval_rejected(self):
        with self.assertRaises(ValidationError):
            self.review(reviewer=self.owner)
        with self.assertRaises(ValidationError):
            self.review(actor=self.operator, reviewer=self.owner)
        review = self.review()
        with self.assertRaises(PermissionDenied):
            decide_review(actor=self.owner, review=review, outcome="approved", note="Self")

    def test_reviewer_must_be_manager_and_have_current_matter_access(self):
        with self.assertRaises(PermissionDenied):
            self.review(reviewer=self.operator)
        secret_doc = Document.objects.create(organization=self.org, matter=self.secret, title="Arquivo reservado", created_by=self.owner)
        secret_version = add_document_version(document=secret_doc, actor=self.owner, file=SimpleUploadedFile("s.txt", b"Secret"))
        with self.assertRaises(ValidationError):
            self.review(version=secret_version)
        self.secret.members.add(self.reviewer)
        review = self.review(version=secret_version)
        self.secret.members.remove(self.reviewer)
        with self.assertRaises(PermissionDenied):
            decide_review(actor=self.reviewer, review=review, outcome="approved", note="Lost access")

    def test_rejection_blocks_publication_and_decision_is_immutable(self):
        review = self.review()
        decision = decide_review(actor=self.reviewer, review=review, outcome="rejected", note="Corrigir nome.")
        with self.assertRaises(ValidationError):
            publish_version(actor=self.owner, review=review, access=self.access(), title="Inadequado")
        with self.assertRaises(ValidationError):
            decide_review(actor=self.reviewer, review=review, outcome="approved", note="Trocar decisão")
        decision.outcome = "approved"
        with self.assertRaises(ValidationError):
            decision.save()
        with self.assertRaises(ValidationError):
            ReviewDecision.objects.filter(pk=decision.pk).update(outcome="approved")

    def test_tenant_and_wrong_contact_grants_rejected(self):
        with self.assertRaises(PermissionDenied):
            self.access(contact=self.other_contact)
        with self.assertRaises(PermissionDenied):
            self.access(membership=self.outsider_membership)
        unrelated = Contact.objects.create(organization=self.org, name="Sem pasta")
        with self.assertRaises(PermissionDenied):
            self.access(contact=unrelated)
        with self.assertRaises(ValidationError):
            self.access(membership=self.viewer_membership)

    def test_other_client_and_outside_tenant_cannot_enumerate_publications(self):
        publication = self.publication()
        for user in [self.second_client, self.outsider]:
            self.client.force_login(user)
            for name in ["publication", "download"]:
                self.assertEqual(self.client.get(reverse("portal:" + name, args=[publication.pk])).status_code, 404)

    def test_revocation_denies_download_and_preserves_review(self):
        publication = self.publication()
        revoke(actor=self.owner, record=publication, reason="Compartilhamento encerrado")
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(reverse("portal:download", args=[publication.pk])).status_code, 404)
        self.assertEqual(DocumentReview.objects.count(), 1)
        self.assertEqual(ReviewDecision.objects.count(), 1)
        publication.refresh_from_db()
        with self.assertRaises(ValidationError):
            publication.delete()
        publication.revoked_at = None
        publication.revoked_by = None
        publication.revoke_reason = ""
        with self.assertRaises(ValidationError):
            publication.save()

    def test_grant_revocation_and_membership_deactivation_remove_access(self):
        publication = self.publication()
        self.client_user_membership.is_active = False
        self.client_user_membership.save()
        self.assertFalse(visible_publications(self.client_user, self.org).exists())
        self.client_user_membership.is_active = True
        self.client_user_membership.save()
        revoke(actor=self.owner, record=publication.access, reason="Identidade deve ser reconferida")
        self.assertFalse(visible_publications(self.client_user, self.org).exists())

    def test_client_changed_on_matter_revokes_current_visibility(self):
        self.publication()
        self.matter.client = Contact.objects.create(organization=self.org, name="Novo cliente")
        self.matter.save()
        self.assertFalse(visible_publications(self.client_user, self.org).exists())

    def test_confidentiality_change_requires_explicit_matter_permission(self):
        publication = self.publication()
        self.matter.confidential = True
        self.matter.save()
        self.assertFalse(visible_publications(self.client_user, self.org).exists())
        self.matter.members.add(self.client_user)
        self.assertTrue(visible_publications(self.client_user, self.org).filter(pk=publication.pk).exists())
        self.matter.members.remove(self.client_user)
        with self.assertRaises(ValidationError):
            publish_version(actor=self.owner, review=publication.review, access=publication.access, title="Ainda sigiloso")

    def test_corrupted_bytes_block_approval_and_download(self):
        publication = self.publication()
        Path(self.version.file.path).write_bytes(b"Tampered")
        with self.assertRaises(Http404):
            verified_source(self.version)
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(reverse("portal:download", args=[publication.pk])).status_code, 404)
        with self.assertRaises(Http404):
            self.review()

    def test_messages_are_scoped_and_escaped(self):
        publication = self.publication()
        message = send_message(actor=self.client_user, publication=publication, body="<script>unsafe()</script>")
        with self.assertRaises(PermissionDenied):
            send_message(actor=self.second_client, publication=publication, body="Intruso")
        self.client.force_login(self.owner)
        page = self.client.get(reverse("portal:publication", args=[publication.pk]))
        self.assertContains(page, "&lt;script&gt;unsafe()&lt;/script&gt;")
        self.assertNotContains(page, "<script>unsafe()</script>")
        with self.assertRaises(ValidationError):
            message.delete()
        revoke(actor=self.owner, record=publication, reason="Finalizado")
        with self.assertRaises(PermissionDenied):
            send_message(actor=self.client_user, publication=publication, body="Depois")

    def test_grant_and_publication_retries_do_not_duplicate(self):
        access = self.access()
        self.assertEqual(self.access().pk, access.pk)
        review = self.approved()
        first = publish_version(actor=self.owner, review=review, access=access, title="Primeiro")
        second = publish_version(actor=self.owner, review=review, access=access, title="Reenvio")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.title, "Primeiro")

    def test_all_internal_pages_render_and_client_is_denied(self):
        publication = self.publication()
        urls = [reverse("portal:manage"), reverse("portal:access_create"), reverse("portal:review_create"), reverse("portal:review", args=[publication.review_id]), reverse("portal:publish", args=[publication.review_id]), reverse("portal:publication_revoke", args=[publication.pk]), reverse("portal:access_revoke", args=[publication.access_id])]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.client_user)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_post_workflow_through_forms_and_csrf(self):
        access_response = self.client.post(reverse("portal:access_create"), {"membership": self.client_user_membership.pk, "contact": self.contact.pk, "confirmed": "on"})
        self.assertEqual(access_response.status_code, 302)
        response = self.client.post(reverse("portal:review_create"), {"version": self.version.pk, "reviewer": self.reviewer.pk, "note": "Conferir", "confirmed": "on"})
        self.assertEqual(response.status_code, 302)
        review = DocumentReview.objects.get()
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(reverse("portal:review", args=[review.pk])), "Sua decisão")
        response = self.client.post(reverse("portal:review", args=[review.pk]), {"outcome": "approved", "note": "Conferido", "confirmed": "on"})
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.owner)
        response = self.client.post(reverse("portal:publish", args=[review.pk]), {"access": ClientAccess.objects.get().pk, "title": "Título para cliente", "note": "Disponível", "confirmed": "on"})
        self.assertEqual(response.status_code, 302)
        from django.test import Client
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(reverse("portal:publication_revoke", args=[Publication.objects.get().pk]), {"reason": "Tentativa sem token"}).status_code, 403)

    def test_start_and_expired_block_writes_preserve_download_and_security_revocation(self):
        publication = self.publication()
        subscription = OrganizationSubscription.objects.create(organization=self.org, plan="start", status="active")
        with override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            with self.assertRaises(PermissionDenied):
                self.review()
            subscription.plan = "max"
            subscription.expires_at = timezone.now()
            subscription.save()
            self.client.force_login(self.client_user)
            self.assertEqual(self.client.get(reverse("portal:home")).status_code, 200)
            response = self.client.get(reverse("portal:download", args=[publication.pk]))
            self.assertEqual(response.status_code, 200)
            # Consume through Django's test-client iterator: it closes the
            # response while preserving TestCase's PostgreSQL transaction.
            self.assertEqual(b"".join(response.streaming_content), b"Exact immutable bytes")
            with self.assertRaises(PermissionDenied):
                send_message(actor=self.client_user, publication=publication, body="Bloqueada")
            revoke(actor=self.owner, record=publication, reason="Revogação continua permitida")
            self.assertFalse(visible_publications(self.client_user, self.org).exists())

    def test_export_helper_excludes_client_and_forbidden_confidential_matter(self):
        publication = self.publication()
        for model in [ClientAccess, DocumentReview, ReviewDecision, Publication, PortalMessage]:
            self.assertFalse(scoped_portal_queryset(self.client_user, self.org, model).exists())
        self.assertTrue(scoped_portal_queryset(self.owner, self.org, Publication).filter(pk=publication.pk).exists())
        self.matter.confidential = True
        self.matter.save()
        self.assertFalse(scoped_portal_queryset(self.operator, self.org, Publication).exists())

    def test_anonymous_requires_login_and_readers_have_no_internal_portal(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("portal:home")).status_code, 302)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("portal:manage")).status_code, 403)

    def test_client_cannot_use_internal_legal_routes_even_as_explicit_secret_member(self):
        self.secret.members.add(self.client_user)
        self.client.force_login(self.client_user)
        self.assertRedirects(self.client.get(reverse("legal:dashboard")), reverse("portal:home"))
        for url in [reverse("legal:detail", args=[self.secret.pk]),
                    reverse("legal:list", args=["contacts"]), reverse("legal:calendar"),
                    reverse("legal:export"), reverse("legal:document_download", args=[self.version.pk]),
                    reverse("contracts:library")]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_staff_cannot_send_to_deactivated_or_changed_recipient(self):
        publication = self.publication()
        self.client_user_membership.is_active = False
        self.client_user_membership.save()
        with self.assertRaises(PermissionDenied):
            send_message(actor=self.owner, publication=publication, body="Destinatário inativo")
        self.client_user_membership.is_active = True
        self.client_user_membership.role = "operator"
        self.client_user_membership.save()
        with self.assertRaises(PermissionDenied):
            send_message(actor=self.owner, publication=publication, body="Perfil alterado")

    def test_unapproved_review_and_empty_notes_are_blocked(self):
        review = self.review()
        with self.assertRaises(ValidationError):
            publish_version(actor=self.owner, review=review, access=self.access(), title="Ainda não aprovado")
        with self.assertRaises(ValidationError):
            decide_review(actor=self.reviewer, review=review, outcome="approved", note="  ")
        self.assertFalse(ReviewDecision.objects.exists())
        self.assertFalse(Publication.objects.exists())


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency is verified on PostgreSQL.")
@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class PortalConcurrencyTests(TransactionTestCase):
    """Real separate connections, not a sequential simulation of concurrent clicks."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        override = override_settings(PRIVATE_MEDIA_ROOT=self.directory.name)
        override.enable()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(override.disable)
        self.org = Organization.objects.create(name="Concurrent portal", slug="portal-concurrent", business_type="office")
        for name, role in [("owner", "owner"), ("reviewer", "manager"), ("client_user", "client")]:
            user = get_user_model().objects.create_user(email=f"{name}@concurrent.example.test")
            setattr(self, name, user)
            membership = Membership.objects.create(organization=self.org, user=user, role=role)
            setattr(self, name + "_membership", membership)
        self.contact = Contact.objects.create(organization=self.org, name="Concurrent client")
        self.matter = Matter.objects.create(organization=self.org, owner=self.owner, client=self.contact, title="Concurrent matter")
        document = Document.objects.create(organization=self.org, matter=self.matter, created_by=self.owner, title="Concurrent document")
        version = add_document_version(document=document, actor=self.owner, file=SimpleUploadedFile("c.txt", b"concurrent bytes"))
        self.review = request_review(actor=self.owner, organization=self.org, version=version, reviewer=self.reviewer, note="Review")
        self.access = grant_access(actor=self.owner, organization=self.org, membership=self.client_user_membership, contact=self.contact)

    def race(self, first, second):
        gate = Barrier(2)

        def execute(operation):
            close_old_connections()
            try:
                gate.wait(timeout=15)
                return operation()
            except (ValidationError, PermissionDenied) as error:
                return error
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(execute, operation) for operation in (first, second)]
            return [future.result(timeout=30) for future in futures]

    def approve(self):
        return decide_review(actor=self.reviewer, review=self.review, outcome="approved", note="Conferido")

    def publish(self):
        return publish_version(actor=self.owner, review=self.review, access=self.access, title="Aprovado")

    def test_concurrent_decisions_keep_exactly_one_immutable_outcome(self):
        results = self.race(self.approve, lambda: decide_review(actor=self.reviewer, review=self.review, outcome="rejected", note="Ajustar"))
        self.assertEqual(ReviewDecision.objects.count(), 1)
        self.assertEqual(sum(isinstance(item, ValidationError) for item in results), 1)

    def test_concurrent_publications_are_idempotent(self):
        self.approve()
        results = self.race(self.publish, self.publish)
        self.assertEqual(Publication.objects.count(), 1)
        self.assertEqual(results[0].pk, results[1].pk)

    def test_whole_contact_revocation_wins_visibility_during_publication(self):
        self.approve()
        results = self.race(self.publish, lambda: revoke(actor=self.owner, record=self.access, reason="Retirar acesso"))
        self.assertFalse(visible_publications(self.client_user, self.org).exists())
        self.access.refresh_from_db()
        self.assertIsNotNone(self.access.revoked_at)
        self.assertTrue(any(isinstance(item, ClientAccess) for item in results))
