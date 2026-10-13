import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.legal.models import ImmutableTenantModel


class TaskComment(ImmutableTenantModel):
    task = models.ForeignKey("legal.Task", on_delete=models.PROTECT, related_name="comments")
    body = models.TextField("Comentário", max_length=3000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="task_comments")
    created_at = models.DateTimeField(auto_now_add=True)
    operation_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def clean(self):
        super().clean()
        if not self.body.strip():
            raise ValidationError({"body": "Escreva um comentário antes de publicar."})
        if len(self.body) > 3000:
            raise ValidationError({"body": "Use até 3.000 caracteres por comentário."})

    def __str__(self):
        return f"Comentário #{self.pk} · tarefa #{self.task_id}"
