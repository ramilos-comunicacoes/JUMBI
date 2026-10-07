"""Quarantine inherited platform access in the isolated JUMBI database clone."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q

from apps.core.models import Membership, User


RESERVED_EMAILS = ("admin@jumbi.nabio.pro", "demo@jumbi.nabio.pro")


def connected_database_name():
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            return cursor.fetchone()[0]
    return str(connection.settings_dict["NAME"])


class Command(BaseCommand):
    help = "Simula por padrão o isolamento de contas herdadas no clone JUMBI. Não apaga registros ou senhas."

    def add_arguments(self, parser):
        parser.add_argument("--expected-db", required=True, help="Nome exato do banco conectado; o banco original djumbi é sempre recusado.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Confirma a desativação e remoção de privilégios no banco indicado.")
        mode.add_argument("--dry-run", action="store_true", help="Apenas mostra contagens, sem alterações (padrão).")

    def handle(self, *args, **options):
        database = connected_database_name()
        if database.casefold() == "djumbi":
            raise CommandError("O banco original djumbi não pode receber este comando. Use o clone isolado.")
        if options["expected_db"] != database:
            raise CommandError("O banco conectado não corresponde a --expected-db. Nenhuma alteração realizada.")

        apply = options["apply"]
        active_office = Membership.objects.filter(
            user_id=OuterRef("pk"), is_active=True,
            organization__business_type="office", organization__status="active",
        )
        reserved = Q()
        for email in RESERVED_EMAILS:
            reserved |= Q(email__iexact=email)
        users = User.objects.exclude(reserved).annotate(has_active_office=Exists(active_office)).order_by("pk")
        totals = {"reviewed": 0, "deactivated": 0, "privileges_removed": 0}
        with transaction.atomic():
            if apply:
                users = users.select_for_update()
            for user in users:
                totals["reviewed"] += 1
                deactivate = user.is_active and not user.has_active_office
                privileged = user.is_staff or user.is_superuser or user.groups.exists() or user.user_permissions.exists()
                totals["deactivated"] += int(deactivate)
                totals["privileges_removed"] += int(bool(privileged))
                if apply:
                    changes = {}
                    if deactivate:
                        changes["is_active"] = False
                    if user.is_staff:
                        changes["is_staff"] = False
                    if user.is_superuser:
                        changes["is_superuser"] = False
                    if changes:
                        User.objects.filter(pk=user.pk).update(**changes)
                    user.groups.clear()
                    user.user_permissions.clear()

        mode = "APLICADO" if apply else "SIMULAÇÃO SEM ALTERAÇÕES"
        self.stdout.write(f"{mode} · banco={database}")
        self.stdout.write(f"Contas herdadas revisadas: {totals['reviewed']}")
        self.stdout.write(f"Contas desativadas: {totals['deactivated']}")
        self.stdout.write(f"Contas com privilégios removidos: {totals['privileges_removed']}")
        self.stdout.write("Registros, vínculos e hashes de senha preservados; contas reservadas excluídas da operação.")
