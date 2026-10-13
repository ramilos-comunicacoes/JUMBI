from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError

from apps.legal.models import Task
from apps.legal.services import _authorize_write, audit
from .models import TaskComment


def visible_comments(user, organization):
    from apps.legal.views import scoped_queryset
    return TaskComment.objects.filter(organization=organization, task__in=scoped_queryset(user, organization, Task))


@transaction.atomic
def comment_on_task(*, actor, task, body, operation_key):
    task = Task.objects.select_for_update().get(pk=task.pk, organization_id=task.organization_id)
    _authorize_write(actor=actor, obj=task)
    body = (body or "").strip()
    try:
        key = UUID(str(operation_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Atualize a página antes de publicar o comentário.") from None
    existing = TaskComment.objects.filter(operation_key=key).first()
    if existing:
        if (existing.task_id, existing.created_by_id, existing.body) != (task.pk, actor.pk, body):
            raise ValidationError("Esta identificação já foi utilizada. Atualize a página.")
        return existing
    try:
        with transaction.atomic():
            obj = TaskComment.objects.create(organization=task.organization, task=task, body=body, created_by=actor, operation_key=key)
    except IntegrityError:
        # Requests against different tasks do not share a row lock. A duplicate
        # global operation key must remain a validation error, not a 500.
        if TaskComment.objects.filter(operation_key=key).exists():
            raise ValidationError("Esta identificação já foi utilizada. Atualize a página.") from None
        raise
    audit(organization=task.organization, actor=actor, action="task.commented", obj=obj, description=f"Comentário adicionado à tarefa #{task.pk}.")
    return obj
