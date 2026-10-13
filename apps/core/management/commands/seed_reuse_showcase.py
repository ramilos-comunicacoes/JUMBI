"""Fictional v5 examples, only in the reserved Max demonstration workspace."""
import os
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.billing.services import check_capacity
from apps.core.models import Membership, Organization, User
from apps.fees.models import FeePlan
from apps.fees.services import create_plan
from apps.legal.models import AuditEvent, Contact, Document, Matter
from apps.legal.services import add_document_version, audit
from apps.portal.models import ReviewDecision
from apps.portal.services import decide_review, grant_access, publish_version, request_review
from apps.routines.catalog import EXAMPLES
from apps.routines.models import RoutineTemplate
from apps.routines.services import add_comment, apply_template, save_template, set_checklist_status


MARKER = "platform.reuse_showcase_seeded_v5"
PREVIOUS_MARKER = "platform.workspace_showcase_seeded_v1"
PREFIX = "DEMONSTRAÇÃO · "
MATTER_TITLE = PREFIX + "Assessoria cível"
ROUTINE_TITLE = PREFIX + "Primeiro atendimento v5"
FEE_TITLE = PREFIX + "Honorários parcelados v5"
DOCUMENT_TITLE = PREFIX + "Orientação fictícia para o portal v5"


class Command(BaseCommand):
    help = "Adiciona exemplos fictícios v5 de rotinas, honorários e portal, sem substituir dados ou senhas existentes."

    def add_arguments(self, parser):
        parser.add_argument("--organization", default="jumbi-demonstracao", choices=["jumbi-demonstracao", "jumbi-demonstracao-local"])

    def _reserved_user(self, *, organization, email, role, first_name, last_name, password=None):
        user = User.objects.select_for_update().filter(email__iexact=email).first()
        if user:
            membership = Membership.objects.filter(user=user, organization=organization).first()
            if (not user.is_active or user.is_staff or user.is_superuser or not membership
                    or not membership.is_active or membership.role != role
                    or user.first_name != first_name or user.last_name != last_name
                    or Membership.objects.filter(user=user).exclude(organization=organization).exists()):
                raise CommandError("A identidade reservada conflita com uma conta ou vínculo existente. Nenhum acesso foi modificado.")
            if role == "manager" and (user.has_usable_password() or user.first_name != first_name or user.last_name != last_name):
                raise CommandError("O colaborador reservado já existe com outra identificação ou senha utilizável. Nenhuma conta foi alterada.")
            return user, membership
        if role == "client":
            if not password:
                raise CommandError("Defina JUMBI_DEMO_CLIENT_PASSWORD para criar a primeira conta de cliente da demonstração.")
            candidate = User(email=email, first_name=first_name, last_name=last_name)
            try:
                validate_password(password, user=candidate)
            except ValidationError:
                raise CommandError("JUMBI_DEMO_CLIENT_PASSWORD não atende à política de senhas. Nenhuma conta foi criada.") from None
        check_capacity(organization, "members")
        user = User.objects.create_user(email=email, password=password if role == "client" else None,
            first_name=first_name, last_name=last_name)
        membership = Membership.objects.create(organization=organization, user=user, role=role)
        return user, membership

    def handle(self, *args, **options):
        slug = options["organization"]
        if slug not in {"jumbi-demonstracao", "jumbi-demonstracao-local"}:
            raise CommandError("Somente a organização reservada de demonstração pode receber esta carga.")
        local = slug.endswith("-local")
        if local and not settings.DEBUG:
            raise CommandError("A carga local exige DEBUG. Nenhum dado foi alterado.")
        created_version = None
        try:
            with transaction.atomic():
                organization = Organization.objects.select_for_update().filter(slug=slug).first()
                if not organization or organization.business_type != "office" or organization.status != "active":
                    raise CommandError("O escritório de demonstração precisa existir e estar ativo no segmento jurídico.")
                subscription = OrganizationSubscription.objects.select_for_update().filter(organization=organization).first()
                if not subscription or subscription.plan != "max" or subscription.status != "demo" or not subscription.is_available:
                    raise CommandError("A carga exige assinatura Max, em demonstração e vigente.")
                suffix = "jumbi.local" if local else "jumbi.nabio.pro"
                owner_member = Membership.objects.select_related("user").filter(
                    organization=organization, user__email__iexact=f"demo@{suffix}", is_active=True,
                    role__in=["owner", "manager"], user__is_active=True,
                ).first()
                if (not owner_member or owner_member.user.is_staff or owner_member.user.is_superuser
                        or Membership.objects.filter(user=owner_member.user).exclude(organization=organization).exists()):
                    raise CommandError("A conta demo reservada deve ser exclusiva deste escritório, ativa e sem privilégios de plataforma.")
                actor = owner_member.user
                if AuditEvent.objects.filter(organization=organization, action=MARKER).exists():
                    self.stdout.write("Exemplos v5 já preparados. Registros, progresso, vínculos e senhas foram preservados.")
                    return
                if not AuditEvent.objects.filter(organization=organization, action=PREVIOUS_MARKER).exists():
                    raise CommandError("Prepare primeiro os exemplos fictícios de seed_workspace_showcase. Nenhuma pasta comum será reutilizada.")
                # Lock the two concrete rows separately. A nullable client FK
                # creates an outer join that PostgreSQL cannot lock wholesale.
                matter = Matter.objects.select_for_update().filter(
                    organization=organization, title=MATTER_TITLE, owner=actor, confidential=False,
                ).exclude(status="closed").first()
                if matter and matter.client_id:
                    contact = Contact.objects.select_for_update().filter(pk=matter.client_id, organization=organization).first()
                    if contact is None:
                        raise CommandError("O contato da pasta fictícia não pertence à demonstração. Nenhum registro foi alterado.")
                    matter.client = contact
                if (not matter or not matter.client or matter.client.organization_id != organization.pk
                        or matter.client.name != PREFIX + "Ana — Civil"
                        or matter.client.email != "showcase-civil@example.invalid"
                        or matter.client.document != "FICTÍCIO-1"
                        or "inteiramente fictícios" not in matter.description):
                    raise CommandError("A pasta e o contato reservados da demonstração estão ausentes ou foram personalizados. Nenhuma pessoa real será reutilizada.")
                if (RoutineTemplate.objects.filter(organization=organization, title=ROUTINE_TITLE).exists()
                        or FeePlan.objects.filter(organization=organization, title=FEE_TITLE).exists()
                        or Document.objects.filter(organization=organization, title=DOCUMENT_TITLE).exists()):
                    raise CommandError("Há registros com nomes reservados sem o marcador v5. Nenhum registro foi substituído.")

                helper, _ = self._reserved_user(organization=organization, email=f"colaborador.demo.v5@{suffix}",
                    role="manager", first_name="DEMONSTRAÇÃO", last_name="Colaborador sem acesso por senha")
                client, client_member = self._reserved_user(organization=organization, email=f"cliente.demo@{suffix}",
                    role="client", first_name="DEMONSTRAÇÃO", last_name="Cliente do portal",
                    password=os.environ.get("JUMBI_DEMO_CLIENT_PASSWORD"))

                example = EXAMPLES["acolhimento"]
                template = save_template(actor=actor, organization=organization, data={
                    **example, "title": ROUTINE_TITLE, "is_active": True,
                    "description": "Rotina inteiramente fictícia para explorar tarefas, conferências e documentos no JUMBI.",
                    "tasks": [PREFIX + title for title in example["tasks"]],
                    "checklist": [PREFIX + title for title in example["checklist"]],
                    "documents": [PREFIX + title for title in example["documents"]],
                })
                application, _ = apply_template(actor=actor, organization=organization, matter_id=matter.pk,
                    template_id=template.pk, expected_version=template.version, task_due_date=timezone.localdate())
                item = application.items.filter(kind="check").first()
                set_checklist_status(actor=actor, item=item, done=True, expected_version=item.version,
                    note="Conferência fictícia concluída para demonstrar evidência e histórico. Nenhum atendimento real.")
                add_comment(actor=actor, matter=matter,
                    body="DEMONSTRAÇÃO: rotina aplicada e primeira conferência concluída. Este comentário é fictício, interno e preservado no histórico.")
                plan = create_plan(organization=organization, actor=actor, matter=matter, client=matter.client,
                    title=FEE_TITLE, kind=FeePlan.Kind.INSTALLMENTS, amount=Decimal("1200.00"), periods=3,
                    first_due_date=timezone.localdate(), operation_key=uuid5(NAMESPACE_URL, f"jumbi:{slug}:showcase-v5-fees"),
                    notes="DEMONSTRAÇÃO: três parcelas fictícias de R$ 400,00. Nenhuma cobrança, recebimento ou mensagem externa foi realizada.")

                document = Document.objects.create(organization=organization, matter=matter,
                    title=DOCUMENT_TITLE, kind="Demonstração fictícia", created_by=helper)
                created_version = add_document_version(document=document, actor=helper, file=SimpleUploadedFile(
                    "demonstracao-portal-v5.txt",
                    ("DEMONSTRAÇÃO — DOCUMENTO INTEIRAMENTE FICTÍCIO\n\n"
                     "Este arquivo demonstra o fluxo de revisão independente e publicação autorizada no portal JUMBI.\n"
                     "Não representa cliente, contratação, orientação jurídica, assinatura ou processo real.\n"
                     "A pessoa cliente vê somente documentos explicitamente publicados para o seu contato.\n"
                     "Nenhuma mensagem externa ou cobrança foi realizada.\n").encode("utf-8"), content_type="text/plain"))
                review = request_review(actor=helper, organization=organization, version=created_version,
                    reviewer=actor, note="DEMONSTRAÇÃO: conferir o exemplo fictício e autorizar sua publicação de teste.")
                decide_review(actor=actor, review=review, outcome=ReviewDecision.Outcome.APPROVED,
                    note="DEMONSTRAÇÃO: revisão independente fictícia concluída sobre esta versão e seu hash.")
                access = grant_access(actor=actor, organization=organization, membership=client_member, contact=matter.client)
                publication = publish_version(actor=actor, review=review, access=access, title=DOCUMENT_TITLE,
                    note="DEMONSTRAÇÃO: este documento é fictício e foi publicado para você após uma revisão independente. Use o portal para conhecer o fluxo.")
                audit(organization=organization, actor=actor, action=MARKER,
                    description=f"Demonstração v5 fictícia: rotina #{application.pk}, honorários #{plan.pk}, publicação #{publication.pk} e conta de cliente #{client.pk}. Nenhuma senha existente redefinida, mensagem externa ou cobrança executada.")
        except Exception:
            # Storage does not participate in the SQL rollback. Only this newly
            # created random-path file may be removed if a later action fails.
            if created_version is not None and created_version.file:
                created_version.file.storage.delete(created_version.file.name)
            raise
        self.stdout.write(self.style.SUCCESS("Demonstração v5 preparada: rotina, conferência, honorários em 3 parcelas e documento revisado no portal. Senhas existentes preservadas; nenhuma mensagem externa enviada."))
