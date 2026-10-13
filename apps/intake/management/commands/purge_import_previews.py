from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.intake.models import ImportBatch


class Command(BaseCommand):
    help = "Remove as prévias não confirmadas que expiraram após 24 horas. Preserva comprovantes concluídos."

    def handle(self, *args, **options):
        count, _ = ImportBatch.objects.filter(committed_at__isnull=True, expires_at__lte=timezone.now()).delete()
        self.stdout.write(self.style.SUCCESS(f"Prévias expiradas removidas: {count}."))
