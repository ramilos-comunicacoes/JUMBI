"""Copy office records without modifying or granting access to their sources.

The default is a complete validation inside a rolled-back transaction. Existing
provenance makes retries harmless; a changed legacy source requires manual review.
"""

import json
from collections import Counter

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from apps.core.models import Membership, Organization, User
from apps.legal.models import (
    Contact, CourtCase, Deadline, FinanceEntry, LegacyImportRecord, Matter, Payment, Task,
)
from apps.legal.services import audit
from apps.office.models import (
    Client, LegalCase, LegalDocument, OfficeFinanceEntry, OfficePurchase, StaffMember, WorkItem,
)


def snapshot(source):
    values = {field.attname: field.value_from_object(source) for field in source._meta.concrete_fields}
    # No documents are imported here; source models have no authentication data.
    return json.loads(json.dumps(values, cls=DjangoJSONEncoder, ensure_ascii=False))


class OfficeImporter:
    def __init__(self, organization, actor=None):
        self.organization = organization
        self.actor = actor
        self.counts = Counter()
        self.pending = []
        self.memberships = Membership.objects.filter(
            organization=organization, is_active=True, user__is_active=True,
        ).select_related("user")
        owner = self.memberships.filter(role=Membership.Role.OWNER).order_by("pk").first()
        if owner is None:
            raise CommandError(f"Organização {organization.pk}: é necessário um proprietário ativo para atribuição dos registros.")
        self.owner = owner.user
        if actor and not self.memberships.filter(user=actor, role__in=["owner", "manager"]).exists():
            raise CommandError(f"O operador informado não integra a direção/gestão da organização {organization.pk}.")

    def queryset(self, model):
        return model.objects.filter(organization=self.organization).order_by("pk")

    def warn(self, source, message):
        self.pending.append(f"{source._meta.label_lower}#{source.pk}: {message}")

    def save_mapping(self, source, model, values, suffix=""):
        key = source._meta.label_lower + suffix
        data = snapshot(source)
        existing = LegacyImportRecord.objects.filter(
            organization=self.organization, source_model=key, source_id=source.pk,
        ).first()
        if existing:
            if existing.source_data != data:
                raise CommandError(f"{key}#{source.pk}: origem mudou após importação; reconciliar manualmente antes de continuar.")
            if existing.target_model != model._meta.label_lower:
                raise CommandError(f"{key}#{source.pk}: destino da importação não corresponde ao esperado.")
            target = model.objects.filter(pk=existing.target_id, organization=self.organization).first()
            if target is None:
                raise CommandError(f"{key}#{source.pk}: destino da importação está ausente.")
            self.counts["já importados"] += 1
            return target
        target = model.objects.create(organization=self.organization, **values)
        LegacyImportRecord.objects.get_or_create(
            organization=self.organization, source_model=key, source_id=source.pk,
            defaults=dict(source_data=data, target_model=model._meta.label_lower, target_id=target.pk, actor=self.actor),
        )
        audit(
            organization=self.organization, actor=self.actor, action="legacy.imported", obj=target,
            description=f"Importação de {key}#{source.pk}. Origem integral preservada no cadastro anterior e no registro de importação.",
        )
        self.counts[model._meta.label_lower] += 1
        return target

    def mapped(self, source, model):
        if source.organization_id != self.organization.pk:
            raise CommandError(f"{source._meta.label_lower}#{source.pk}: referência entre organizações; revisão necessária.")
        record = LegacyImportRecord.objects.get(
            organization=self.organization, source_model=source._meta.label_lower, source_id=source.pk,
        )
        return model.objects.get(pk=record.target_id, organization=self.organization)

    def active_owner(self, source, user_id=None):
        membership = self.memberships.filter(user_id=user_id).first() if user_id else None
        if membership:
            return membership.user
        if user_id:
            self.warn(source, "responsável anterior sem vínculo ativo; atribuído ao proprietário do escritório.")
        return self.owner

    def reference_date(self, source, value):
        if value:
            return value
        self.warn(source, "data ausente; data de criação usada somente como referência administrativa, sujeita a revisão.")
        return timezone.localdate(source.created_at)

    def import_contact(self, source):
        return self.save_mapping(source, Contact, dict(name=source.name, email=source.email, phone=source.phone))

    def import_case(self, source):
        owner = self.owner
        if source.responsible_id:
            if source.responsible.organization_id != self.organization.pk:
                raise CommandError(f"office.legalcase#{source.pk}: responsável pertence a outra organização.")
            membership = self.memberships.filter(user__email__iexact=source.responsible.email).first() if source.responsible.email else None
            if source.responsible.is_active and membership:
                owner = membership.user
            else:
                self.warn(source, "responsável anterior sem usuário ativo correspondente; atribuído ao proprietário.")
        nature = {"judicial": "litigation", "administrative": "administrative"}.get(source.nature, "advisory")
        description = source.description + "\n\nOrigem: cadastro anterior (office.legalcase).\n" + json.dumps(snapshot(source), ensure_ascii=False, indent=2)
        matter = self.save_mapping(source, Matter, dict(
            title=source.title, client=self.mapped(source.client, Contact) if source.client_id else None,
            owner=owner, nature=nature, area=source.practice_area.name if source.practice_area_id else "",
            status={"closed": "closed", "waiting": "waiting"}.get(source.status, "active"),
            confidential=source.confidential, description=description,
        ))
        if source.case_number and source.nature in ["judicial", "administrative"]:
            self.save_mapping(source, CourtCase, dict(
                matter=matter, number=source.case_number, court=source.court,
                opposing_party=source.opposing_party,
                notes="Número transcrito do legado sem validação de formato CNJ. Conferência necessária.",
            ), suffix=":court")
        if source.next_deadline:
            self.warn(source, "próximo prazo importado como pendente de conferência humana.")
            self.save_mapping(source, Deadline, dict(
                matter=matter, owner=matter.owner, title=f"Conferir próximo prazo: {source.title}",
                due_date=source.next_deadline,
                source=f"Importação manual do cadastro anterior; conferência pendente. office.legalcase#{source.pk}, campo next_deadline. Natureza: {source.nature}; estágio: {source.stage}.",
            ), suffix=":next_deadline")
        return matter

    def related_matter(self, source, owner=None):
        if getattr(source, "case_id", None):
            return self.mapped(source.case, Matter)
        # A source with a client gets an explicit administrative folder, preserving
        # the relation without claiming a judicial case exists.
        client = self.mapped(source.client, Contact) if getattr(source, "client_id", None) else None
        return self.save_mapping(source, Matter, dict(
            title=f"Cadastro anterior · {getattr(source, 'title', getattr(source, 'description', str(source)))}"[:240],
            client=client, owner=owner or self.owner, nature=Matter.Nature.ADVISORY,
            description=f"Pasta administrativa para preservar vínculo de {source._meta.label_lower}#{source.pk}; origem sem processo vinculado.",
        ), suffix=":matter")

    def import_work(self, source):
        owner = self.active_owner(source, source.owner_id)
        matter = self.related_matter(source, owner)
        if matter.confidential and matter.owner_id != owner.pk and not matter.members.filter(pk=owner.pk).exists():
            owner = matter.owner
            self.warn(source, "pasta sigilosa: responsável mantido no proprietário autorizado da pasta, sem ampliar acesso.")
        raw = json.dumps(snapshot(source), ensure_ascii=False, indent=2)
        if source.kind == "deadline" and source.due_date:
            self.warn(source, "prazo permanece pendente de conferência, independentemente da situação anterior.")
            self.save_mapping(source, Deadline, dict(
                matter=matter, title=source.title, owner=owner, due_date=source.due_date,
                source="Importação manual do cadastro anterior; conferência pendente.\n" + raw,
            ))
            return
        needs_review = source.kind in ["deadline", "hearing", "appointment"]
        reason = ""
        if source.kind in ["hearing", "appointment"]:
            reason = "Horário de início/fim ausente no cadastro anterior. Conferir a data e registrar na agenda; nenhum horário foi presumido."
        elif source.kind == "deadline":
            reason = "Vencimento ausente no cadastro anterior. A data desta tarefa é referência administrativa, não prazo jurídico."
        if reason:
            self.warn(source, reason)
        due_date = self.reference_date(source, source.due_date)
        status = "todo" if needs_review else {"in_progress": "doing", "done": "done"}.get(source.status, "todo")
        self.save_mapping(source, Task, dict(
            matter=matter, title=(f"Conferir cadastro anterior: {source.title}" if needs_review else source.title)[:240],
            description=reason + "\nOrigem preservada:\n" + raw,
            owner=owner, due_date=due_date, priority=source.priority, status=status,
            completion_note="Registro legado marcado concluído; evidência anterior não informada." if status == "done" else "",
        ))

    def import_finance(self, source, purchase=False):
        if source.amount <= 0:
            raise CommandError(f"{source._meta.label_lower}#{source.pk}: valor não positivo exige conciliação manual; nenhum valor foi corrigido automaticamente.")
        if purchase:
            description = f"Compra: {source.item} · {source.supplier_name}"[:240]
            kind = FinanceEntry.Kind.EXPENSE
            date = self.reference_date(source, source.purchased_at)
            matter = None
        else:
            description = source.description
            kind = FinanceEntry.Kind.INCOME if source.kind == "revenue" else FinanceEntry.Kind.EXPENSE
            date = self.reference_date(source, source.due_date)
            matter = self.related_matter(source)
        entry = self.save_mapping(source, FinanceEntry, dict(
            matter=matter, description=description, kind=kind, amount=source.amount, due_date=date,
        ))
        if source.paid:
            self.import_settlement(source, entry)

    def import_settlement(self, source, entry):
        self.warn(source, "baixa importada sem data, operador ou comprovação documental; conferir o registro anterior.")
        self.save_mapping(source, Payment, dict(
            entry=entry, amount=source.amount, date=None, created_by=None, is_legacy_import=True,
            note=(f"Baixa importada do legado sem comprovação documental. {source._meta.label_lower}#{source.pk} "
                  "estava marcado como pago. Data de pagamento e operador original não informados; "
                  "saldo reproduz o cadastro anterior, sujeito a conciliação. O autor desta importação "
                  "consta na auditoria e não é apresentado como autor do pagamento."),
        ), suffix=":settlement")

    def run(self):
        if self.queryset(LegalDocument).exists():
            raise CommandError(
                f"Organização {self.organization.pk}: documentos legados exigem migração e verificação de arquivos privados antes de importar; operação cancelada."
            )
        for source in self.queryset(Client):
            self.import_contact(source)
        for source in self.queryset(StaffMember):
            self.import_contact(source)
            self.warn(source, "cadastro de colaborador preservado como pessoa; permissões e vínculo de acesso não foram criados.")
        for source in self.queryset(LegalCase).select_related("responsible", "client", "practice_area"):
            self.import_case(source)
        for source in self.queryset(WorkItem).select_related("case", "client"):
            self.import_work(source)
        for source in self.queryset(OfficeFinanceEntry).select_related("case", "client"):
            self.import_finance(source)
        for source in self.queryset(OfficePurchase):
            self.import_finance(source, purchase=True)


class Command(BaseCommand):
    help = "Importa office para legal preservando proveniência e sigilo. Sem --apply, valida e desfaz todas as alterações."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Confirma a cópia após validação; não altera a origem.")
        mode.add_argument("--dry-run", action="store_true", help="Valida sem persistir (padrão).")
        parser.add_argument("--organization-id", type=int, action="append", help="ID do escritório; pode ser repetido.")
        parser.add_argument("--actor-email", help="Operador real, membro ativo da gestão; omitido registra migração de sistema.")

    def handle(self, *args, **options):
        actor = None
        if options.get("actor_email"):
            actor = User.objects.filter(email__iexact=options["actor_email"], is_active=True).first()
            if not actor:
                raise CommandError("Operador informado não encontrado ou inativo.")
        organizations = Organization.objects.filter(business_type="office").order_by("pk")
        requested = options.get("organization_id")
        if requested:
            organizations = organizations.filter(pk__in=requested)
            if set(organizations.values_list("pk", flat=True)) != set(requested):
                raise CommandError("Um dos IDs não corresponde a organização jurídica existente.")
        reports = []
        try:
            with transaction.atomic():
                for organization in organizations.select_for_update():
                    importer = OfficeImporter(organization, actor)
                    importer.run()
                    reports.append((organization.pk, importer.counts, importer.pending))
                if not options["apply"]:
                    transaction.set_rollback(True)
        except ValidationError as exc:
            raise CommandError(f"Validação impediu a importação; todas as alterações foram desfeitas: {exc}") from exc
        self.stdout.write("APLICADO" if options["apply"] else "SIMULAÇÃO — nenhuma alteração persistida")
        for org_id, counts, pending in reports:
            self.stdout.write(f"Organização {org_id}: " + (", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "sem registros"))
            self.stdout.write(f"Pendências de conferência: {len(pending)}")
            for message in pending:
                self.stdout.write(f"  - {message}")
