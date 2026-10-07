"""Explicitly create fictional, local-only data for UI and pilot verification."""
import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from apps.core.models import Membership, Organization, User
from apps.legal.models import Appointment, Contact, CourtCase, Deadline, Document, FinanceEntry, Matter, Opportunity, Task
from apps.legal.services import add_document_version, audit, confirm_deadline, record_payment


class Command(BaseCommand):
    help = "Cria dados fictícios do piloto, somente em DEBUG. Senha via JUMBI_DEMO_PASSWORD."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="demo@jumbi.local")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("A demonstração não pode ser carregada em produção.")
        if Organization.objects.filter(slug="jumbi-demonstracao-local").exists():
            self.stdout.write("Demonstração já criada. Nenhum registro ou senha foi alterado.")
            return
        password = os.environ.get("JUMBI_DEMO_PASSWORD")
        if not password or len(password) < 12:
            raise CommandError("Defina JUMBI_DEMO_PASSWORD com pelo menos 12 caracteres.")
        if User.objects.filter(email__iexact=options["email"]).exists():
            raise CommandError("E-mail já cadastrado. Use um e-mail exclusivo da demonstração.")
        user = User.objects.create_user(options["email"], password=password, first_name="Marina", last_name="Almeida")
        org = Organization.objects.create(name="Almeida Advocacia · Demonstração", slug="jumbi-demonstracao-local", business_type="office", contact_email=user.email)
        Membership.objects.create(organization=org, user=user, role="owner")
        from apps.billing.models import OrganizationSubscription
        OrganizationSubscription.objects.create(organization=org, plan="max", status="demo")
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
            audit(organization=org, actor=user, action="matter.created", obj=matter, description="Pasta criada na demonstração local.")
        CourtCase.objects.create(organization=org, matter=matters[2], number="DEMO-2026-001", court="Órgão de demonstração", opposing_party="Parte fictícia", notes="Número fictício; nenhuma consulta externa foi executada.")
        for index, title in enumerate(["Revisar minuta contratual", "Solicitar documentos ao cliente", "Preparar reunião de alinhamento", "Conferir documentos recebidos", "Organizar evidências do atendimento", "Revisar cláusulas comerciais"]):
            Task.objects.create(organization=org, matter=matters[index % 5], title=title, owner=user, due_date=today + timedelta(days=index - 1), priority="high" if index == 0 else "normal", status="doing" if index in {0, 2} else "todo")
        for index, title in enumerate(["Conferência de obrigação processual", "Entrega da revisão contratual", "Manifestação administrativa"]):
            deadline = Deadline.objects.create(organization=org, matter=matters[index], title=title, source="Registro manual fictício. Data informada para demonstração, sem cálculo jurídico automático.", due_date=today + timedelta(days=index + 1), owner=user)
            if index < 2:
                confirm_deadline(deadline=deadline, actor=user)
        start = timezone.now().replace(hour=17, minute=0, second=0, microsecond=0) + timedelta(days=1)
        Appointment.objects.create(organization=org, matter=matters[1], title="Alinhamento com o cliente", starts_at=start, ends_at=start + timedelta(hours=1), location="Reunião online", owner=user)
        for index, stage in enumerate(["new", "qualification", "proposal"]):
            Opportunity.objects.create(organization=org, contact=contacts[index], title=["Consultoria contratual", "Assessoria recorrente", "Revisão de documentos"][index], stage=stage, amount=Decimal(["2500", "4800", "1800"][index]), owner=user, next_action="Agendar conversa inicial com o contato.")
        entry = FinanceEntry.objects.create(organization=org, matter=matters[0], description="Honorários de revisão contratual", kind="income", amount=Decimal("1000"), due_date=today + timedelta(days=4))
        record_payment(entry=entry, actor=user, amount=Decimal("350"), note="Recebimento parcial fictício para demonstrar o saldo de R$ 650,00.")
        FinanceEntry.objects.create(organization=org, matter=matters[1], description="Assessoria empresarial mensal", kind="income", amount=Decimal("4800"), due_date=today + timedelta(days=8))
        FinanceEntry.objects.create(organization=org, description="Serviços administrativos", kind="expense", amount=Decimal("240"), due_date=today + timedelta(days=3))
        document = Document.objects.create(organization=org, matter=matters[0], title="Orientações da demonstração", kind="Anotação", created_by=user)
        add_document_version(document=document, actor=user, file=SimpleUploadedFile("leia-me.txt", "Este documento é fictício e privado. O download exige autenticação e acesso à pasta.\n".encode(), content_type="text/plain"))
        self.stdout.write(self.style.SUCCESS(f"Demonstração criada para {user.email}. A senha veio do ambiente e não foi exibida."))
