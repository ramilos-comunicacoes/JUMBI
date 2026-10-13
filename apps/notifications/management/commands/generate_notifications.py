from django.core.management.base import BaseCommand

from apps.core.models import Membership
from apps.notifications.services import OFFICE_ROLES, generate_for_user


class Command(BaseCommand):
    help = "Atualiza lembretes internos persistentes; não envia mensagens externas."

    def handle(self, *args, **options):
        total = 0
        memberships = Membership.objects.filter(
            is_active=True, user__is_active=True, role__in=OFFICE_ROLES,
            organization__status="active", organization__business_type="office",
        ).select_related("user", "organization")
        for membership in memberships.iterator(chunk_size=100):
            total += generate_for_user(membership.user, membership.organization)
        self.stdout.write(self.style.SUCCESS(f"Central atualizada: {total} nova(s) ocorrência(s)."))
