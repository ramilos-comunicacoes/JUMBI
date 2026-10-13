"""Optional fictional samples. Never repairs, overwrites or replenishes records."""
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.billing.models import OrganizationSubscription
from apps.core.models import Membership, Organization
from apps.inventory.models import Asset, Category, Movement, Product, Purchase, Supplier
from apps.inventory.services import create_purchase, record_movement, require_inventory_access, save_record
from apps.legal.models import AuditEvent
from apps.legal.services import audit


DEMO_TARGETS = {
    "jumbi-demonstracao": "demo@jumbi.nabio.pro",
    "jumbi-demonstracao-local": "demo@jumbi.local",
}
ACTION = "inventory.demo_seeded"
CATEGORY_NAME = "[DEMONSTRAÇÃO] Suprimentos do escritório"
SUPPLIER_NAME = "[DEMONSTRAÇÃO] Papelaria Exemplo"
PRODUCT_CODES = ("DEMO-PAPEL", "DEMO-TONER")
ASSET_CODES = ("DEMO-NOTEBOOK", "DEMO-IMPRESSORA")
PURCHASE_REFERENCE = "[DEMONSTRAÇÃO] Compra de suprimentos 001"
REASON = "[DEMONSTRAÇÃO] Dados fictícios para explorar o módulo de inventário e estoque."


def operation_key(slug, operation):
    return uuid5(NAMESPACE_URL, f"jumbi:inventory-demo:v1:{slug}:{operation}")


class Command(BaseCommand):
    help = "Prévia de dados fictícios de estoque. Exige --apply para cadastrar, exclusivamente nos escritórios demo autorizados."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, help="Slug exato do escritório de demonstração autorizado.")
        parser.add_argument("--email", required=True, help="E-mail exato do gestor da demonstração autorizada.")
        parser.add_argument("--apply", action="store_true", help="Cadastrar os exemplos após conferir permissões e conflitos.")

    def _check_conflicts(self, organization):
        conflicts = []
        checks = (
            (Category.objects.filter(organization=organization, name__iexact=CATEGORY_NAME), "categoria"),
            (Supplier.objects.filter(organization=organization, name__iexact=SUPPLIER_NAME), "fornecedor"),
            (Product.objects.filter(organization=organization, code__in=PRODUCT_CODES), "código de material"),
            (Asset.objects.filter(organization=organization, code__in=ASSET_CODES), "etiqueta patrimonial"),
            (Purchase.objects.filter(organization=organization, reference=PURCHASE_REFERENCE), "referência de compra"),
            (Purchase.objects.filter(organization=organization, operation_key=operation_key(organization.slug, "purchase")), "identificação da compra"),
            (Movement.objects.filter(organization=organization, operation_key__in=[operation_key(organization.slug, code) for code in PRODUCT_CODES]), "identificação de movimentação"),
        )
        for queryset, label in checks:
            if queryset.exists():
                conflicts.append(label)
        if conflicts:
            raise CommandError("Há registros que conflitam com os exemplos (" + ", ".join(conflicts) + "). Nenhum dado foi alterado. Confira os registros manualmente; o comando não sobrescreve nem completa cadastros parciais.")

    def _seed(self, organization, actor):
        category = save_record(instance=Category(organization=organization, name=CATEGORY_NAME), actor=actor, reason=REASON)
        supplier = save_record(instance=Supplier(organization=organization, name=SUPPLIER_NAME), actor=actor, reason=REASON)
        paper = save_record(instance=Product(organization=organization, code=PRODUCT_CODES[0], name="[DEMONSTRAÇÃO] Papel A4", category=category, unit="pct", location="[DEMONSTRAÇÃO] Armário de suprimentos", minimum_stock=Decimal("3")), actor=actor, reason=REASON)
        toner = save_record(instance=Product(organization=organization, code=PRODUCT_CODES[1], name="[DEMONSTRAÇÃO] Toner para impressora", category=category, unit="un", location="[DEMONSTRAÇÃO] Armário de suprimentos", minimum_stock=Decimal("2")), actor=actor, reason=REASON)
        for product, quantity in [(paper, "10.000"), (toner, "1.000")]:
            record_movement(organization=organization, actor=actor, product=product, kind="entry", quantity=quantity,
                lot_code="DEMO-ABERTURA", reason=REASON, operation_key=operation_key(organization.slug, product.code))
        create_purchase(organization=organization, actor=actor, supplier=supplier, reference=PURCHASE_REFERENCE,
            purchased_on=timezone.localdate(), notes=REASON + " Aguardando conferência e recebimento; não representa pagamento.",
            operation_key=operation_key(organization.slug, "purchase"), items=[
                dict(product=paper, quantity="6.000", unit_cost="25.00", lot_code="DEMO-COMPRA-001"),
                dict(product=toner, quantity="2.000", unit_cost="180.00", lot_code="DEMO-COMPRA-001"),
            ])
        for code, name, value, status, location in [
            (ASSET_CODES[0], "Notebook da equipe", "4500.00", Asset.Status.IN_USE, "Sala de atendimento"),
            (ASSET_CODES[1], "Impressora do escritório", "1200.00", Asset.Status.MAINTENANCE, "Bancada de manutenção"),
        ]:
            save_record(instance=Asset(organization=organization, code=code, name=f"[DEMONSTRAÇÃO] {name}",
                location=f"[DEMONSTRAÇÃO] {location}", custodian=actor, acquisition_value=Decimal(value), status=status,
                notes=REASON), actor=actor, reason=REASON)
        audit(organization=organization, actor=actor, action=ACTION,
            description=REASON + " Pacote v1: 2 materiais, 2 lotes, 2 entradas, 1 compra pendente e 2 bens. Reexecuções preservam todos os dados existentes.")

    def handle(self, *args, **options):
        slug, email = options["organization"], options["email"]
        if slug not in DEMO_TARGETS or email != DEMO_TARGETS[slug]:
            raise CommandError("Use somente o par exato de escritório/e-mail da demonstração autorizada. Escritórios reais não são aceitos.")
        try:
            with transaction.atomic():
                organizations = Organization.objects.select_for_update() if options["apply"] else Organization.objects.all()
                organization = organizations.filter(slug=slug, business_type="office", status="active").first()
                if organization is None:
                    raise CommandError("O escritório de demonstração não existe ou não está ativo.")
                actor = get_user_model().objects.filter(email=email, is_active=True).first()
                if actor is None or not Membership.objects.filter(organization=organization, user=actor, is_active=True, role__in=["owner", "manager"]).exists():
                    raise CommandError("O usuário de demonstração precisa estar ativo com perfil de direção ou gestão neste escritório.")
                subscription = OrganizationSubscription.objects.filter(organization=organization, status="demo", plan="max").first()
                if subscription is None or not subscription.is_available:
                    raise CommandError("O escritório precisa de assinatura Max em demonstração vigente.")
                require_inventory_access(actor, organization)
                marker = AuditEvent.objects.filter(organization=organization, action=ACTION, object_type="core.organization", object_id=str(organization.pk)).exists()
                if marker:
                    self.stdout.write("Exemplos já cadastrados. Nenhum registro foi alterado ou reabastecido.")
                    return
                self._check_conflicts(organization)
                if not options["apply"]:
                    self.stdout.write("PRÉVIA: 1 categoria; 1 fornecedor; 2 materiais; 2 lotes; 2 entradas; 1 compra pendente com 2 itens; 2 bens e seus históricos. Nenhum dado alterado. Use --apply para cadastrar.")
                    return
                self._seed(organization, actor)
        except (PermissionDenied, ValidationError) as exc:
            detail = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            raise CommandError(f"Demonstração não cadastrada; todas as alterações foram revertidas. {detail}") from exc
        self.stdout.write(self.style.SUCCESS("Demonstração cadastrada: 2 materiais, 2 lotes, 1 compra pendente e 2 bens. Nenhuma despesa ou pagamento foi registrado."))
