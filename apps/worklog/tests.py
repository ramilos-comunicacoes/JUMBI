import io
import json
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings, RequestFactory, Client, skipUnlessDBFeature
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Membership, Organization, User
from apps.core.test_platform import TEST_SETTINGS
from apps.legal.models import Contact, Matter, Task, Document, FinanceEntry
from apps.legal.services import add_document_version, audit
from .models import TaskComment
from .services import comment_on_task, visible_comments


@override_settings(**TEST_SETTINGS)
class CollaborationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Equipe", slug="comments-team", business_type="office")
        cls.other = Organization.objects.create(name="Outra equipe", slug="comments-other", business_type="office")
        cls.owner = User.objects.create_user("owner@comments.test", "OnlyForTests!129")
        cls.operator = User.objects.create_user("operator@comments.test", "OnlyForTests!130")
        cls.viewer = User.objects.create_user("viewer@comments.test", "OnlyForTests!131")
        cls.platform = User.objects.create_superuser("platform@comments.test", "OnlyForTests!132")
        for user, role in [(cls.owner, 'owner'), (cls.operator, 'operator'), (cls.viewer, 'viewer')]:
            Membership.objects.create(organization=cls.org, user=user, role=role)
        Membership.objects.create(organization=cls.other, user=cls.platform, role='owner')
        cls.contact = Contact.objects.create(organization=cls.org, name="Pessoa", trade_name="Nome de contato", city="Fortaleza")
        cls.matter = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Pasta A")
        cls.sibling = Matter.objects.create(organization=cls.org, owner=cls.owner, client=cls.contact, title="Pasta B")
        cls.secret = Matter.objects.create(organization=cls.org, owner=cls.owner, title="Pasta restrita", confidential=True)
        cls.task = Task.objects.create(organization=cls.org, owner=cls.operator, matter=cls.matter, title="Entrega", due_date=timezone.localdate())
        cls.secret_task = Task.objects.create(organization=cls.org, owner=cls.owner, matter=cls.secret, title="Entrega reservada", due_date=timezone.localdate())

    def setUp(self):
        self.client.force_login(self.operator)

    def comment(self, **kwargs):
        return comment_on_task(**{'actor': self.operator, 'task': self.task, 'body': 'Atualização da equipe', 'operation_key': uuid4(), **kwargs})

    def test_comment_is_idempotent_audited_and_immutable(self):
        key=uuid4()
        obj=self.comment(operation_key=key)
        self.assertEqual(self.comment(operation_key=key).pk, obj.pk)
        with self.assertRaises(ValidationError): self.comment(operation_key=key, body="Alteração silenciosa")
        with self.assertRaises(ValidationError): obj.delete()
        with self.assertRaises(ValidationError): TaskComment.objects.filter(pk=obj.pk).update(body="Outra")
        self.assertEqual(TaskComment.objects.count(), 1)
        self.assertTrue(self.org.legal_auditevent_records.filter(action='task.commented', object_id=str(obj.pk)).exists())

    def test_comment_respects_readonly_sigilo_tenant_and_revocation(self):
        for actor, task in [(self.viewer,self.task),(self.platform,self.task),(self.operator,self.secret_task)]:
            with self.assertRaises(PermissionDenied): self.comment(actor=actor,task=task)
        self.comment()
        Membership.objects.filter(user=self.operator,organization=self.org).update(is_active=False)
        self.assertFalse(visible_comments(self.operator,self.org).exists())
        with self.assertRaises(PermissionDenied): self.comment()

    def test_comment_rejects_empty_and_overlong(self):
        for body in ['  ', 'x'*3001]:
            with self.assertRaises(ValidationError): self.comment(body=body)
        self.assertFalse(TaskComment.objects.exists())

    def test_detail_http_post_and_readonly(self):
        url=reverse('worklog:task',args=[self.task.pk])
        self.assertContains(self.client.get(url), "Publicar comentário")
        self.assertEqual(self.client.post(url, {'body':'Atualização salva', 'operation_key':uuid4()}).status_code, 302)
        self.assertContains(self.client.get(url), 'Atualização salva')
        self.client.force_login(self.viewer)
        self.assertNotContains(self.client.get(url), 'Publicar comentário')
        self.assertEqual(self.client.post(url, {'body':'Proibido', 'operation_key':uuid4()}).status_code,403)
        self.assertEqual(self.client.get(reverse('worklog:task',args=[self.secret_task.pk])).status_code,404)

    def test_csrf_and_escaped_body(self):
        url=reverse('worklog:task',args=[self.task.pk])
        csrf_client=Client(enforce_csrf_checks=True); csrf_client.force_login(self.operator)
        self.assertEqual(csrf_client.post(url, {'body':'Sem token','operation_key':uuid4()}).status_code,403)
        self.comment(body='<script>alert(1)</script>')
        response=self.client.get(url)
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_expired_subscription_blocks_comment_service(self):
        with override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            with self.assertRaises(PermissionDenied): self.comment()

    def export(self, user, matter=None):
        self.client.force_login(user)
        response=self.client.get(reverse('legal:export_matter',args=[matter.pk]) if matter else reverse('legal:export'))
        self.assertEqual(response.status_code,200)
        archive=zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))
        self.addCleanup(archive.close)
        return json.loads(archive.read('records.json')), json.loads(archive.read('manifest.json')), archive

    def test_matter_export_keeps_exact_scope_files_hashes_comments_and_profile(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(PRIVATE_MEDIA_ROOT=directory):
            doc=Document.objects.create(organization=self.org,matter=self.matter,title='Arquivo A',created_by=self.owner)
            version=add_document_version(document=doc,actor=self.owner,file=SimpleUploadedFile('prova.txt',b'prova original'))
            siblingdoc=Document.objects.create(organization=self.org,matter=self.sibling,title='Arquivo B',created_by=self.owner)
            add_document_version(document=siblingdoc,actor=self.owner,file=SimpleUploadedFile('outra.txt',b'fora da pasta'))
            self.comment()
            audit(organization=self.org,actor=self.owner,action='matter.updated',obj=self.sibling,description='Fora do recorte')
            records,manifest,archive=self.export(self.operator,self.matter)
            self.assertEqual([r['id'] for r in records['matter']],[self.matter.pk])
            self.assertEqual([r['id'] for r in records['document']],[doc.pk])
            self.assertEqual(records['contact'][0]['city'],'Fortaleza')
            self.assertEqual(len(records['taskcomment']),1)
            self.assertEqual(manifest['matter']['id'],self.matter.pk)
            self.assertEqual(records['documentversion'][0]['checksum'],version.checksum)
            self.assertEqual(archive.read(records['documentversion'][0]['archive_path']),b'prova original')
            self.assertNotIn('Fora do recorte',archive.read('records.json').decode())
            self.assertEqual(records['product'],[])
            self.assertNotIn('financeentry',records)

    def test_matter_zip_refuses_secret_and_maintains_portability(self):
        self.assertEqual(self.client.get(reverse('legal:export_matter',args=[self.secret.pk])).status_code,404)
        with override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            self.export(self.operator,self.matter)

    def test_whole_office_export_includes_comments(self):
        self.comment()
        records,_,_=self.export(self.owner)
        self.assertEqual(len(records['taskcomment']),1)

    def test_inventory_portability_is_role_limited_and_preserves_asset_history(self):
        from apps.inventory.models import Product, Asset
        from apps.inventory.services import save_record, record_movement
        product=save_record(instance=Product(organization=self.org,code='SUPPLY',name='Papel'),actor=self.owner)
        record_movement(organization=self.org,actor=self.owner,product=product,kind='entry',quantity='5',lot_code='INIT',reason='Conferência inicial',operation_key=uuid4())
        asset=save_record(instance=Asset(organization=self.org,code='ASSET',name='Computador',custodian=self.operator),actor=self.owner)
        asset.custodian=self.owner
        save_record(instance=asset,actor=self.owner,reason='Transferência de responsabilidade')
        with override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=True):
            records,_,_=self.export(self.owner)
        self.assertEqual(records['stocklot'][0]['quantity'],'5.000')
        self.assertEqual(len(records['assetevent']),2)
        self.assertIn(self.operator.pk,{row['id'] for row in records['users']})
        readonly,_,_=self.export(self.operator)
        self.assertEqual(readonly['product'],[])
        self.assertEqual(readonly['assetevent'],[])

    def test_admin_has_no_platform_or_confidential_bypass(self):
        modeladmin=admin.site._registry[Matter]
        request=RequestFactory().get('/admin/'); request.user=self.platform; request.organization=self.org
        self.assertFalse(modeladmin.get_queryset(request).exists())
        Membership.objects.create(organization=self.org,user=self.platform,role='manager')
        self.assertEqual(set(modeladmin.get_queryset(request).values_list('pk',flat=True)),{self.matter.pk,self.sibling.pk})
        self.assertFalse(modeladmin.has_view_permission(request,self.secret))
        self.secret.members.add(self.platform)
        self.assertTrue(modeladmin.has_view_permission(request,self.secret))

    def test_admin_operator_cannot_read_finance(self):
        Membership.objects.create(organization=self.org,user=self.platform,role='operator')
        FinanceEntry.objects.create(organization=self.org,matter=self.matter,description='Restrito',amount='90.00',due_date=timezone.localdate())
        request=RequestFactory().get('/admin/'); request.user=self.platform; request.organization=self.org
        self.assertFalse(admin.site._registry[FinanceEntry].get_queryset(request).exists())


@override_settings(**TEST_SETTINGS)
class CommentConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_same_operation_key_on_different_tasks_returns_validation_not_server_error(self):
        org=Organization.objects.create(name='Comentários concorrentes',slug='comment-concurrency',business_type='office')
        actor=User.objects.create_user('parallel@comments.test')
        Membership.objects.create(organization=org,user=actor,role='operator')
        tasks=[Task.objects.create(organization=org,owner=actor,title=f'Tarefa {i}',due_date=timezone.localdate()) for i in range(2)]
        barrier=Barrier(2); key=uuid4()
        def worker(task):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    comment_on_task(actor=actor,task=task,body='Atualização',operation_key=key)
                    return 'ok'
                except ValidationError:
                    return 'rejected'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker, task) for task in tasks]
            self.assertCountEqual([future.result(timeout=30) for future in futures],['ok','rejected'])
        self.assertEqual(TaskComment.objects.count(),1)
