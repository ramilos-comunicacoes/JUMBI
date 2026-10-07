import secrets
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.office.models import (
    Client,
    LegalCase,
    MatterType,
    OfficeFinanceEntry,
    OfficePurchase,
    PracticeArea,
    StaffMember,
    WorkItem,
)

from ...models import Membership, Organization, User


class Command(BaseCommand):
    help = "Cria o administrador e um escritório jurídico demonstrativo do Jumbi."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="admin@jumbi.local")
        parser.add_argument("--password")

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"].lower()
        user, created = User.objects.get_or_create(
            email=email,
            defaults={"is_staff": True, "is_superuser": True},
        )
        password = None
        if created or options["password"]:
            password = options["password"] or secrets.token_urlsafe(18)
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save()

        office, _ = Organization.objects.get_or_create(
            slug="demo-office",
            defaults={
                "name": "Horizonte Advocacia",
                "legal_name": "Horizonte Sociedade de Advogados",
                "business_type": Organization.BusinessType.OFFICE,
                "city": "Fortaleza",
                "state": "CE",
                "status": Organization.Status.ACTIVE,
            },
        )
        if office.business_type != Organization.BusinessType.OFFICE:
            office.business_type = Organization.BusinessType.OFFICE
            office.save(update_fields=["business_type", "updated_at"])
        Membership.objects.get_or_create(
            organization=office,
            user=user,
            defaults={"role": Membership.Role.OWNER},
        )

        client, _ = Client.objects.get_or_create(
            organization=office,
            name="Marina Almeida",
            defaults={"email": "marina@exemplo.local", "phone": "(85) 99999-1000"},
        )
        lawyer, _ = StaffMember.objects.get_or_create(
            organization=office,
            name="Dra. Helena Costa",
            defaults={"role": StaffMember.Role.LAWYER, "email": "helena@horizonte.local"},
        )
        legal_case, _ = LegalCase.objects.get_or_create(
            organization=office,
            title="Revisão contratual empresarial",
            defaults={
                "client": client,
                "court": "Consultivo",
                "status": LegalCase.Status.ACTIVE,
                "responsible": lawyer,
            },
        )
        contract_area = PracticeArea.objects.filter(slug="contratos").first()
        contract_type = MatterType.objects.filter(
            practice_area=contract_area,
            slug="revisao-negociacao",
        ).first()
        legal_case_updates = []
        if contract_area and legal_case.practice_area_id is None:
            legal_case.practice_area = contract_area
            legal_case_updates.append("practice_area")
        if contract_type and legal_case.matter_type_id is None:
            legal_case.matter_type = contract_type
            legal_case_updates.append("matter_type")
        if legal_case_updates:
            legal_case.nature = LegalCase.Nature.ADVISORY
            legal_case.stage = LegalCase.Stage.IN_PROGRESS
            legal_case_updates.extend(["nature", "stage"])
            legal_case.save(update_fields=legal_case_updates)
        work_item, _ = WorkItem.objects.get_or_create(
            organization=office,
            title="Revisar contrato de prestação de serviços",
            defaults={
                "client": client,
                "case": legal_case,
                "status": WorkItem.Status.IN_PROGRESS,
                "owner": user,
            },
        )
        if work_item.case_id is None:
            work_item.case = legal_case
            work_item.save(update_fields=["case"])
        OfficeFinanceEntry.objects.get_or_create(
            organization=office,
            description="Honorários consultivos",
            defaults={
                "client": client,
                "case": legal_case,
                "kind": OfficeFinanceEntry.Kind.REVENUE,
                "amount": Decimal("8500.00"),
                "paid": False,
            },
        )
        OfficePurchase.objects.get_or_create(
            organization=office,
            supplier_name="Certificado Digital Brasil",
            item="Renovação e-CNPJ",
            defaults={"amount": Decimal("389.90"), "paid": True},
        )

        self.stdout.write(self.style.SUCCESS("Demonstração jurídica do Jumbi pronta."))
        self.stdout.write(f"E-mail do administrador: {email}")
        if password:
            self.stdout.write(self.style.WARNING(f"Senha inicial: {password}"))
            self.stdout.write("Altere esta senha antes de liberar qualquer acesso externo.")
        else:
            self.stdout.write("Administrador já existia; a senha atual foi preservada.")
