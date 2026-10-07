"""Explicit deployment provisioning; credentials are accepted only via environment."""
import os
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from apps.core.models import Membership, Organization, User
from apps.legal.models import (
    Appointment, AuditEvent, Contact, CourtCase, Deadline, Document,
    FinanceEntry, Matter, Opportunity, Task,
)
from apps.legal.services import add_document_version, audit, confirm_deadline, record_payment


class Command(BaseCommand):
    help = "Provisiona administração e demonstração isoladas. Senhas somente por JUMBI_ADMIN_PASSWORD/JUMBI_DEMO_PASSWORD."

    def add_arguments(self, parser):
        parser.add_argument("--admin-email", required=True)
        parser.add_argument("--demo-email", required=True)
        parser.add_argument("--reset-passwords", action="store_true", help="Autoriza explicitamente trocar as senhas das duas contas existentes.")
        parser.add_argument("--with-demo-data", action="store_true", help="Autoriza criar dados fictícios somente no escritório exclusivo de demonstração, inclusive em produção.")

    def handle(self, *args, **options):
        admin_email = options["admin_email"].strip().lower()
        demo_email = options["demo_email"].strip().lower()
        try:
            validate_email(admin_email)
            validate_email(demo_email)
        except ValidationError:
            raise CommandError("Informe e-mails válidos para administração e demonstração.") from None
        if admin_email == demo_email:
            raise CommandError("Administração e demonstração precisam de contas diferentes.")

        self.created_versions = []
        try:
            with transaction.atomic():
                admin_user, admin_org, admin_status = self._account(
                    email=admin_email, password_env="JUMBI_ADMIN_PASSWORD", superuser=True,
                    slug="jumbi-administracao", name="JUMBI · Administração", role="owner",
                    reset=options["reset_passwords"],
                )
                demo_user, demo_org, demo_status = self._account(
                    email=demo_email, password_env="JUMBI_DEMO_PASSWORD", superuser=False,
                    slug="jumbi-demonstracao", name="JUMBI · Demonstração", role="manager",
                    reset=options["reset_passwords"],
                )
                from apps.billing.models import OrganizationSubscription
                OrganizationSubscription.objects.get_or_create(
                    organization=admin_org, defaults={"plan": "max", "status": "active"},
                )
                OrganizationSubscription.objects.get_or_create(
                    organization=demo_org, defaults={"plan": "max", "status": "demo"},
                )
                if options["with_demo_data"]:
                    self._seed_demo(demo_org, demo_user)
        except Exception:
            # Database rollback cannot undo storage writes. Remove only files
            # created by this invocation, never an existing demonstration file.
            for version in self.created_versions:
                version.file.storage.delete(version.file.name)
            raise

        self.stdout.write(self.style.SUCCESS(f"Administração: {admin_user.email} · {admin_status}"))
        self.stdout.write(self.style.SUCCESS(f"Demonstração: {demo_user.email} · {demo_status}"))

    def _account(self, *, email, password_env, superuser, slug, name, role, reset):
        user = User.objects.select_for_update().filter(email__iexact=email).first()
        created = user is None
        if user is not None:
            if not user.is_active or user.is_superuser != superuser or user.is_staff != superuser:
                raise CommandError("Uma conta existente tem permissões incompatíveis. Nenhuma permissão foi alterada.")
            if not superuser and Membership.objects.filter(user=user).exclude(organization__slug=slug).exists():
                raise CommandError("A conta de demonstração já possui acesso a outro escritório. Use um e-mail exclusivo.")
        else:
            user = User(email=email, first_name="Administrador" if superuser else "Marina", last_name="JUMBI" if superuser else "Almeida", is_active=True, is_staff=superuser, is_superuser=superuser)

        if created or reset:
            password = os.environ.get(password_env)
            if not password:
                raise CommandError(f"Defina {password_env} no ambiente para criar ou atualizar esta conta.")
            try:
                validate_password(password, user=user)
            except ValidationError:
                raise CommandError(f"{password_env} não atende à política de senhas configurada.") from None
            user.set_password(password)
            user.save()

        org, org_created = Organization.objects.get_or_create(slug=slug, defaults={
            "name": name, "business_type": "office", "contact_email": email,
        })
        if org.business_type != "office" or org.status != "active":
            raise CommandError("O escritório reservado está suspenso ou possui segmento incompatível.")
        if Membership.objects.filter(organization=org).exclude(user=user).exists():
            raise CommandError("O escritório reservado já possui outros usuários. Nenhum acesso foi alterado.")
        membership, member_created = Membership.objects.get_or_create(organization=org, user=user, defaults={"role": role})
        if not membership.is_active or membership.role != role:
            raise CommandError("O vínculo existente possui um perfil diferente. Nenhum acesso foi alterado.")
        if created or org_created or member_created:
            audit(organization=org, actor=user, action="platform.account_provisioned", description="Conta de administração provisionada." if superuser else "Conta exclusiva de demonstração provisionada.")
        return user, org, "criada" if created else "senha atualizada" if reset else "preservada"

    def _seed_demo(self, org, user):
        if org.slug != "jumbi-demonstracao" or user.is_staff or user.is_superuser:
            raise CommandError("Dados fictícios exigem escritório e conta exclusivos de demonstração.")
        if AuditEvent.objects.filter(organization=org, action="platform.demo_seeded").exists():
            return
        if any(model.objects.filter(organization=org).exists() for model in (Contact, Matter, CourtCase, Task, Deadline, Appointment, Document, FinanceEntry, Opportunity)):
            raise CommandError("A demonstração já contém registros sem marcador de carga. Nenhum dado foi substituído.")

        today = timezone.localdate()
        names = ["Ana Beatriz Costa", "Aurora Comércio Ltda.", "Carlos Eduardo Lima", "Horizonte Tecnologia", "Lúcia Fernandes"]
        contacts = [Contact.objects.create(organization=org, name=name, kind="company" if index in {1, 3} else "person", email=f"contato{index + 1}@example.invalid") for index, name in enumerate(names)]
        details = [
            ("Revisão de contrato de prestação de serviços", "contract", "Contratos", "active"),
            ("Assessoria jurídica empresarial", "advisory", "Empresarial", "active"),
            ("Acompanhamento de demanda cível", "litigation", "Cível", "active"),
            ("Adequação de contratos comerciais", "contract", "Contratos", "waiting"),
            ("Planejamento sucessório", "advisory", "Família e sucessões", "active"),
        ]
        matters = []
        for index, (title, nature, area, status) in enumerate(details):
            matter = Matter.objects.create(organization=org, title=title, client=contacts[index], nature=nature, area=area, status=status, owner=user, description="Registro fictício para explorar os fluxos do JUMBI. Não representa um atendimento real.")
            matters.append(matter)
            audit(organization=org, actor=user, action="matter.created", obj=matter, description="Pasta fictícia criada para demonstração.")
        CourtCase.objects.create(organization=org, matter=matters[2], number="DEMO-001", court="Órgão de demonstração", opposing_party="Parte fictícia", notes="Número fictício; nenhuma consulta externa foi executada.")
        for index, title in enumerate(["Revisar minuta contratual", "Solicitar documentos ao cliente", "Preparar reunião de alinhamento", "Conferir documentos recebidos", "Organizar evidências do atendimento", "Revisar cláusulas comerciais"]):
            Task.objects.create(organization=org, matter=matters[index % 5], title=title, owner=user, due_date=today + timedelta(days=index - 1), priority="high" if index == 0 else "normal", status="doing" if index in {0, 2} else "todo")
        for index, title in enumerate(["Conferência de obrigação processual", "Entrega da revisão contratual", "Manifestação administrativa"]):
            deadline = Deadline.objects.create(organization=org, matter=matters[index], title=title, source="Registro manual fictício. Data informada para demonstração, sem cálculo jurídico automático.", due_date=today + timedelta(days=index + 1), owner=user)
            if index < 2:
                confirm_deadline(deadline=deadline, actor=user)
        start = timezone.localtime().replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1)
        Appointment.objects.create(organization=org, matter=matters[1], title="Alinhamento com o cliente", starts_at=start, ends_at=start + timedelta(hours=1), location="Reunião online", owner=user)
        for index, stage in enumerate(["new", "qualification", "proposal"]):
            Opportunity.objects.create(organization=org, contact=contacts[index], title=["Consultoria contratual", "Assessoria recorrente", "Revisão de documentos"][index], stage=stage, amount=Decimal(["2500", "4800", "1800"][index]), owner=user, next_action="Agendar conversa inicial com o contato.")
        entry = FinanceEntry.objects.create(organization=org, matter=matters[0], description="Honorários de revisão contratual", kind="income", amount=Decimal("1000"), due_date=today + timedelta(days=4))
        record_payment(entry=entry, actor=user, amount=Decimal("350"), note="Recebimento parcial fictício para demonstrar o saldo de R$ 650,00.")
        FinanceEntry.objects.create(organization=org, matter=matters[1], description="Assessoria empresarial mensal", kind="income", amount=Decimal("4800"), due_date=today + timedelta(days=8))
        FinanceEntry.objects.create(organization=org, description="Serviços administrativos", kind="expense", amount=Decimal("240"), due_date=today + timedelta(days=3))
        audit(organization=org, actor=user, action="platform.demo_seeded", description="Dados fictícios de demonstração carregados uma única vez.")
        document = Document.objects.create(organization=org, matter=matters[0], title="Orientações da demonstração", kind="Anotação", created_by=user)
        version = add_document_version(document=document, actor=user, file=SimpleUploadedFile("leia-me.txt", "Este documento é fictício e privado. Use a conta de demonstração para testar os fluxos do JUMBI. Não inclua dados reais de clientes neste escritório.\n".encode(), content_type="text/plain"))
        self.created_versions.append(version)
