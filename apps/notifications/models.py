"""Personal read states for reminders derived from authorized office records."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.legal.models import TenantModel


class Notification(TenantModel):
    class Kind(models.TextChoices):
        DEADLINE = "deadline", "Prazo"
        TASK = "task", "Tarefa"
        BIRTHDAY = "birthday", "Aniversário"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="office_notifications")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    deadline = models.ForeignKey("legal.Deadline", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    task = models.ForeignKey("legal.Task", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    contact = models.ForeignKey("legal.Contact", null=True, blank=True, on_delete=models.CASCADE, related_name="birthday_notifications")
    source_date = models.DateField("Data da ocorrência")
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["organization", "recipient", "dismissed_at", "read_at"], name="notification_inbox_idx")]
        constraints = [
            models.CheckConstraint(condition=(
                Q(kind="deadline", deadline__isnull=False, task__isnull=True, contact__isnull=True)
                | Q(kind="task", task__isnull=False, deadline__isnull=True, contact__isnull=True)
                | Q(kind="birthday", contact__isnull=False, deadline__isnull=True, task__isnull=True)
            ), name="notification_one_subject"),
            models.UniqueConstraint(fields=["organization", "recipient", "deadline", "source_date"], condition=Q(deadline__isnull=False), name="notification_unique_deadline"),
            models.UniqueConstraint(fields=["organization", "recipient", "task", "source_date"], condition=Q(task__isnull=False), name="notification_unique_task"),
            models.UniqueConstraint(fields=["organization", "recipient", "contact", "source_date"], condition=Q(contact__isnull=False), name="notification_unique_birthday"),
        ]

    def clean(self):
        super().clean()
        from apps.core.models import Membership
        if self.recipient_id and self.organization_id and not Membership.objects.filter(
            user_id=self.recipient_id, organization_id=self.organization_id,
            is_active=True, user__is_active=True, role__in=["owner", "manager", "operator", "viewer"],
        ).exists():
            raise ValidationError({"recipient": "O destinatário precisa integrar a equipe ativa deste escritório."})
