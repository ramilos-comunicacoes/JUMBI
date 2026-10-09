"""Add one fictional showcase to the reserved demo workspace, without resets."""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.billing.services import check_capacity
from apps.contracts.catalog import EXAMPLE_BODY, EXAMPLE_TITLE
from apps.contracts.models import ContractTemplate
from apps.contracts.services import generate_revision
from apps.core.models import Membership, Organization
from apps.legal.models import Appointment, AuditEvent, Contact, Deadline, Matter, Task
from apps.legal.services import audit, complete_task, move_task
from apps.performance.models import Goal
from apps.performance.services import record_progress, save_goal


MARKER = "platform.workspace_showcase_seeded_v1"
PREFIX = "DEMONSTRAÇÃO · "
AREAS = ["civil", "familia", "trabalhista", "previdenciario"]
PHONE = "+5588992745456"
TEST_NOTE = (
    "Pessoa e atendimento inteiramente fictícios. O telefone cadastrado é o número comercial "
    "do próprio responsável pelo JUMBI, usado somente para testar a abertura do WhatsApp. "
    "Nenhuma mensagem foi enviada. Não representa contato nem caso de cliente real."
)


class Command(BaseCommand):
    help = "Adiciona exemplos fictícios de calendário, Kanban, metas e contratos somente à demonstração reservada, sem redefinir progresso."

    def add_arguments(self, parser):
        parser.add_argument("--organization", default="jumbi-demonstracao", choices=["jumbi-demonstracao", "jumbi-demonstracao-local"])

    def handle(self, *args, **options):
        slug = options["organization"]
        if slug not in {"jumbi-demonstracao", "jumbi-demonstracao-local"}:
            raise CommandError("Somente o escritório reservado de demonstração pode receber os exemplos.")
        if slug.endswith("-local") and not settings.DEBUG:
            raise CommandError("A demonstração local exige DEBUG; nenhum dado foi alterado.")
        created_version = None
        try:
            with transaction.atomic():
                org = Organization.objects.select_for_update().filter(slug=slug).first()
                if org is None or org.business_type != "office" or org.status != "active":
                    raise CommandError("O escritório de demonstração precisa existir e estar ativo no segmento jurídico.")
                subscription = OrganizationSubscription.objects.select_for_update().filter(organization=org).first()
                if not subscription or subscription.status != "demo" or subscription.plan != "max" or not subscription.is_available:
                    raise CommandError("Os exemplos exigem assinatura Max em estado de demonstração e vigente.")
                memberships = list(Membership.objects.filter(organization=org).select_related("user"))
                if len(memberships) != 1:
                    raise CommandError("A demonstração deve ter exatamente uma conta exclusiva; nenhum acesso foi modificado.")
                membership = memberships[0]
                actor = membership.user
                expected_email = "demo@jumbi.nabio.pro" if slug == "jumbi-demonstracao" else "demo@jumbi.local"
                if (not membership.is_active or membership.role not in {"owner", "manager"}
                        or not actor.is_active or actor.is_staff or actor.is_superuser
                        or actor.email.lower() != expected_email
                        or Membership.objects.filter(user=actor).exclude(organization=org).exists()):
                    raise CommandError("A conta demo reservada precisa estar ativa, sem privilégios de plataforma e sem vínculo com outros escritórios.")
                if AuditEvent.objects.filter(organization=org, action=MARKER).exists():
                    self.stdout.write("Exemplos já preparados. Datas, textos, contas e progresso existentes foram preservados.")
                    return

                # Refuse conflicting reserved names instead of assuming that an
                # existing user-edited record belongs to this new showcase.
                names = [PREFIX + name for name in ["Ana — Civil", "Bruno — Família", "Carla — Trabalhista", "Diego — Previdenciário"]]
                titles = [PREFIX + name for name in ["Assessoria cível", "Planejamento familiar", "Revisão trabalhista", "Orientação previdenciária"]]
                template_name = PREFIX + EXAMPLE_TITLE
                if (Contact.objects.filter(organization=org, name__in=names).exists()
                        or Matter.objects.filter(organization=org, title__in=titles).exists()
                        or ContractTemplate.objects.filter(organization=org, name=template_name).exists()
                        or Goal.objects.filter(organization=org, title__in=[PREFIX + "Atendimentos revisados", PREFIX + "Tarefas concluídas no mês"]).exists()):
                    raise CommandError("Há registros com nomes reservados, mas sem marcador desta carga. Nenhum registro foi reutilizado ou substituído.")

                if not org.practice_areas:
                    org.practice_areas = AREAS.copy()
                    org.save(update_fields=["practice_areas", "updated_at"])
                today = timezone.localdate()
                matters, contacts = [], []
                for index, (name, title, niche, offset) in enumerate(zip(names, titles, AREAS, [0, 1, 3, 5])):
                    birthday = today + timedelta(days=offset)
                    contact = Contact.objects.create(
                        organization=org, name=name, kind=Contact.Kind.PERSON,
                        email=f"showcase-{niche}@example.invalid", phone=PHONE,
                        document=f"FICTÍCIO-{index + 1}", birth_date=date(1992, birthday.month, birthday.day),
                    )
                    matter = Matter(organization=org, title=title, client=contact, area=niche,
                                    nature=Matter.Nature.ADVISORY, owner=actor, description=TEST_NOTE)
                    check_capacity(org, "matters", instance=matter)
                    matter.save()
                    contacts.append(contact)
                    matters.append(matter)
                    audit(organization=org, actor=actor, action="matter.created", obj=matter, description=TEST_NOTE)
                for index, title in enumerate(["Separar documentos", "Preparar atendimento", "Revisar cadastro fictício", "Retomar pendência de teste"]):
                    task = Task.objects.create(
                        organization=org, matter=matters[index], owner=actor, title=PREFIX + title,
                        description="Atividade fictícia para testar movimentações no Kanban. Não é uma obrigação de cliente real.",
                        due_date=today + timedelta(days=-1 if index == 3 else index + 1),
                        priority="high" if index in {1, 3} else "normal",
                    )
                    if index == 1:
                        move_task(task=task, actor=actor, destination="doing", expected_status="todo", note="Início fictício de demonstração.")
                    elif index == 2:
                        complete_task(task=task, actor=actor, evidence="Conferência fictícia concluída para demonstrar o histórico. O prazo da pasta continua independente.")
                Deadline.objects.create(
                    organization=org, matter=matters[2], owner=actor, title=PREFIX + "Conferir prazo independente",
                    source="Data fictícia digitada para demonstração. Não é prazo processual calculado nem publicação real.",
                    due_date=today + timedelta(days=2),
                )
                start = timezone.localtime().replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1)
                for index, (kind, title, offset) in enumerate([
                    (Appointment.Kind.HEARING, "Audiência fictícia", 0),
                    (Appointment.Kind.IMPORTANT_DATE, "Data importante do atendimento", 2),
                ]):
                    moment = start + timedelta(days=offset)
                    Appointment.objects.create(
                        organization=org, matter=matters[index], owner=actor, kind=kind, title=PREFIX + title,
                        starts_at=moment, ends_at=moment + timedelta(hours=1), location="DEMONSTRAÇÃO — sem compromisso real",
                    )
                period_start = today.replace(day=1)
                period_end = (period_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                for metric, title, target in [(Goal.Metric.MANUAL, "Atendimentos revisados", "10"), (Goal.Metric.TASKS, "Tarefas concluídas no mês", "5")]:
                    goal = save_goal(actor=actor, organization=org, data={
                        "title": PREFIX + title, "description": "Indicador fictício para explorar o progresso no painel.",
                        "metric": metric, "target": Decimal(target), "starts_on": period_start, "ends_on": period_end,
                        "owner": actor, "niche": "", "archived": False,
                    })
                    if metric == Goal.Metric.MANUAL:
                        record_progress(actor=actor, organization=org, goal_id=goal.pk, value="3", note="Três atendimentos fictícios revisados para demonstrar atualização manual.")
                template = ContractTemplate.objects.create(
                    organization=org, created_by=actor, name=template_name, category="Demonstração",
                    description="Modelo fictício editável. Revise as cláusulas antes de qualquer utilização profissional.", body=EXAMPLE_BODY,
                )
                revision = generate_revision(
                    actor=actor, organization=org, template=template, matter=matters[0], client=contacts[0],
                    title=PREFIX + "Contrato fictício para revisão", source_body=EXAMPLE_BODY,
                    values={
                        "cliente_nome": contacts[0].name, "cliente_documento": "FICTÍCIO — não representa CPF/CNPJ",
                        "cliente_endereco": "Endereço fictício para demonstração",
                        "escritorio_nome": "DEMONSTRAÇÃO — Escritório fictício JUMBI",
                        "escritorio_documento": "FICTÍCIO — não representa CPF/CNPJ",
                        "escritorio_endereco": "Endereço fictício para demonstração", "advogado_nome": "Profissional fictício",
                        "advogado_oab": "FICTÍCIA — sem inscrição profissional", "pasta_titulo": matters[0].title,
                        "objeto": "Exemplo fictício de descrição dos serviços, com escopo e limites a serem editados pelo profissional.",
                        "honorarios": "Condições fictícias, apenas para demonstrar a edição. Nenhuma cobrança foi criada.",
                        "vigencia": "Período fictício a definir após revisão profissional.",
                        "condicoes": "Não representa contratação real, assinatura ou autorização de representação.",
                        "cidade": "Cidade fictícia", "data": today.strftime("%d/%m/%Y"),
                    },
                )
                created_version = revision.document_version
                audit(organization=org, actor=actor, action=MARKER,
                      description="Exemplos fictícios: 4 pessoas/pastas, 4 tarefas, 1 prazo, 2 eventos, 2 metas e 1 contrato. WhatsApp usa o número comercial do responsável; nada foi enviado.")
        except Exception:
            if created_version is not None and created_version.file:
                created_version.file.storage.delete(created_version.file.name)
            raise
        self.stdout.write(self.style.SUCCESS("Demonstração preparada: calendário, aniversários, Kanban, metas e contrato. Contas, senhas e registros anteriores preservados; nenhuma mensagem enviada."))
