"""Optional fictional contact locations, restricted to the two demo workspaces."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.billing.models import OrganizationSubscription
from apps.billing.services import require_access
from apps.core.models import Membership, Organization
from apps.legal.models import AuditEvent, Contact
from apps.legal.services import audit


DEMO_TARGETS = {
    "jumbi-demonstracao": "demo@jumbi.nabio.pro",
    "jumbi-demonstracao-local": "demo@jumbi.local",
}
ACTION = "client_map.demo_seeded"
NOTES = "[DEMONSTRAÇÃO] Cadastro fictício para explorar o mapa de clientes. A cidade e a UF são exemplos; não identificam uma pessoa ou endereço real. Nenhum contato, documento ou publicação de cliente foi importado."
SAMPLES = (
    ("[DEMONSTRAÇÃO] Mapa · Fortaleza 01", "CE", "Fortaleza"),
    ("[DEMONSTRAÇÃO] Mapa · Fortaleza 02", "CE", "Fortaleza"),
    ("[DEMONSTRAÇÃO] Mapa · São Paulo", "SP", "São Paulo"),
    ("[DEMONSTRAÇÃO] Mapa · Rio de Janeiro", "RJ", "Rio de Janeiro"),
    ("[DEMONSTRAÇÃO] Mapa · Recife", "PE", "Recife"),
    ("[DEMONSTRAÇÃO] Mapa · Brasília", "DF", "Brasília"),
    ("[DEMONSTRAÇÃO] Mapa · Porto Alegre", "RS", "Porto Alegre"),
)


class Command(BaseCommand):
    help = "Mostra uma prévia dos contatos fictícios do mapa; --apply cadastra apenas nos escritórios demo autorizados."

    def add_arguments(self, parser):
        parser.add_argument("--organization", required=True, help="Slug exato do escritório de demonstração autorizado.")
        parser.add_argument("--email", required=True, help="E-mail exato do gestor da demonstração autorizada.")
        parser.add_argument("--apply", action="store_true", help="Cadastrar os exemplos após conferir permissões e conflitos.")

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
                require_access(organization, advanced=True)
                if AuditEvent.objects.filter(organization=organization, action=ACTION, object_type="core.organization", object_id=str(organization.pk)).exists():
                    self.stdout.write("Exemplos do mapa já cadastrados. Nenhum contato foi alterado ou recriado.")
                    return
                reserved_names = {sample[0].casefold() for sample in SAMPLES}
                # Python casefold also handles accented letters consistently on
                # SQLite previews and PostgreSQL. Only this demo office is read.
                # Materialize this reserved demo-only name list before raising:
                # a partially consumed PostgreSQL server cursor can outlive a
                # rolled-back savepoint and poison the surrounding transaction.
                existing_names = list(Contact.objects.filter(organization=organization).values_list("name", flat=True))
                if any(name.casefold() in reserved_names for name in existing_names):
                    raise CommandError("Um nome reservado aos exemplos já está cadastrado. Nenhum dado foi alterado; o comando não sobrescreve nem completa cadastros parciais.")
                if not options["apply"]:
                    self.stdout.write("PRÉVIA: 7 novos cadastros fictícios em 6 UFs (CE: 2; SP: 1; RJ: 1; PE: 1; DF: 1; RS: 1). Nenhum dado alterado. Use --apply para cadastrar.")
                    return
                for name, state, city in SAMPLES:
                    contact = Contact.objects.create(organization=organization, name=name, state=state, city=city,
                        country="Brasil", notes=NOTES, kind=Contact.Kind.PERSON, status=Contact.Status.ACTIVE,
                        email="", phone="", document="", postal_code="", address="", address_complement="", district="")
                    audit(organization=organization, actor=actor, action="contact.demo_created", obj=contact,
                        description="[DEMONSTRAÇÃO] Cadastro fictício com país, UF e capital para explorar o mapa de clientes.")
                audit(organization=organization, actor=actor, action=ACTION,
                    description="[DEMONSTRAÇÃO] Pacote de mapa v1: 7 novos cadastros em CE (2), SP, RJ, PE, DF e RS. Nenhuma pasta ou publicação criada. Reexecuções preservam os registros existentes.")
        except (PermissionDenied, ValidationError) as exc:
            detail = "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            raise CommandError(f"Demonstração não cadastrada; todas as alterações foram revertidas. {detail}") from exc
        self.stdout.write(self.style.SUCCESS("Mapa de demonstração preparado com 7 cadastros fictícios novos em 6 UFs. Nenhum cadastro anterior, pasta ou publicação foi alterado."))
