import uuid

from django.conf import settings
from django.db import models


class ImportBatch(models.Model):
    class Kind(models.TextChoices):
        CONTACTS = "contacts", "Pessoas"
        CASES = "cases", "Processos"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("core.Organization", on_delete=models.CASCADE)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    rows = models.JSONField(default=list)
    columns = models.JSONField(default=list)
    row_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    committed_at = models.DateTimeField(null=True, blank=True)
    created_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "created_by", "-created_at"], name="intake_owner_created_idx")]
