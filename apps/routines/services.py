from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.billing.services import require_access
from apps.core.models import Membership, Organization
from apps.core.niches import practice_area_values
from apps.legal.models import Matter, Task
from apps.legal.services import _authorize_write, audit, can_write, visible_matters
from .catalog import EXAMPLES
from .models import MatterChecklist, MatterComment, RoutineApplication, RoutineTemplate


def can_manage_templates(user, organization):
    return bool(can_write(user, organization) and Membership.objects.filter(
        organization=organization, user=user, is_active=True, role__in=["owner", "manager"],
    ).exists())


def visible_templates(user, organization):
    if not user.is_authenticated or not user.is_active or organization.status != "active" or not Membership.objects.filter(
        user=user, organization=organization, is_active=True, role__in=["owner", "manager", "operator", "viewer"],
    ).exists():
        return RoutineTemplate.objects.none()
    queryset = RoutineTemplate.objects.filter(organization=organization)
    return queryset if can_manage_templates(user, organization) else queryset.filter(is_active=True)


def visible_records(user, organization, model):
    """Subscription-independent scope for the authenticated export service."""
    return model.objects.filter(organization=organization, matter__in=visible_matters(user, organization))


@transaction.atomic
def save_template(*, actor, organization, data, template_id=None, expected_version=None):
    require_access(organization)
    if not can_manage_templates(actor, organization):
        raise PermissionDenied("Somente direção e gestão podem editar modelos de rotina.")
    template = RoutineTemplate.objects.select_for_update().get(pk=template_id, organization=organization) if template_id else RoutineTemplate(organization=organization, created_by=actor)
    if template.pk and template.version != expected_version:
        raise ValidationError("Este modelo foi alterado por outra pessoa. Atualize a página antes de salvar.")
    if any(niche not in organization.practice_areas for niche in data["niches"]):
        raise ValidationError("Escolha apenas áreas de atuação configuradas neste escritório.")
    for key in ("title", "description", "niches", "tasks", "checklist", "documents", "is_active"):
        setattr(template, key, data[key])
    if template.pk:
        template.version += 1
    template.save()
    audit(organization=organization, actor=actor, action="routine.template_saved", obj=template,
          description=f"Modelo de rotina atualizado: {template.title}. Versão {template.version}.")
    return template


@transaction.atomic
def import_example(*, actor, organization, key):
    require_access(organization)
    if not can_manage_templates(actor, organization):
        raise PermissionDenied("Somente direção e gestão podem adicionar modelos ao catálogo.")
    if key not in EXAMPLES:
        raise ValidationError("Escolha um exemplo disponível.")
    # An office lock and unique seed key make repeated submits harmless.
    Organization.objects.select_for_update().get(pk=organization.pk)
    existing = RoutineTemplate.objects.filter(organization=organization, seed_key=key).first()
    if existing:
        return existing
    example = EXAMPLES[key]
    niches = [code for code in example["niches"] if code in organization.practice_areas]
    if example["niches"] and not niches:
        raise ValidationError("Este exemplo pertence a uma área ainda não configurada no escritório.")
    template = RoutineTemplate.objects.create(organization=organization, created_by=actor, seed_key=key,
        **{**example, "niches": niches})
    audit(organization=organization, actor=actor, action="routine.template_imported", obj=template,
          description=f"Exemplo adicionado ao catálogo para revisão da equipe: {template.title}.")
    return template


def _check_match(template, matter):
    if template.niches and matter.area not in [value for code in template.niches for value in practice_area_values(code)]:
        raise ValidationError("A área da pasta deve corresponder a uma das áreas deste modelo.")


@transaction.atomic
def apply_template(*, actor, organization, matter_id, template_id, expected_version, task_due_date=None):
    # All applications to a matter serialize; no duplicate tasks on retries.
    matter = Matter.objects.select_for_update().get(pk=matter_id, organization=organization)
    _authorize_write(actor=actor, obj=matter)
    template = RoutineTemplate.objects.select_for_update().get(pk=template_id, organization=organization)
    previous = RoutineApplication.objects.filter(matter=matter, template=template).first()
    if previous:
        return previous, False
    if not template.is_active:
        raise ValidationError("Este modelo foi arquivado e não aceita novas aplicações.")
    if template.version != expected_version:
        raise ValidationError("O modelo mudou desde a prévia. Revise a versão atual antes de aplicar.")
    _check_match(template, matter)
    if matter.status == Matter.Status.CLOSED:
        raise ValidationError("Reabra a pasta antes de aplicar uma nova rotina.")
    if template.tasks and not isinstance(task_due_date, date):
        raise ValidationError("Escolha uma data operacional para as tarefas.")
    if template.tasks and task_due_date < timezone.localdate():
        raise ValidationError("Escolha hoje ou uma data futura para as novas tarefas.")
    task_ids = []
    for title in template.tasks:
        task = Task.objects.create(organization=organization, matter=matter, title=title, owner=actor,
            due_date=task_due_date, description=f"Rotina: {template.title} · versão {template.version}.\n{template.description}")
        task_ids.append(task.pk)
        audit(organization=organization, actor=actor, action="task.created", obj=task,
              description=f"Tarefa criada pela rotina {template.title}; data operacional {task_due_date}.")
    snapshot = {key: getattr(template, key) for key in ("title", "description", "niches", "tasks", "checklist", "documents")}
    application = RoutineApplication.objects.create(organization=organization, matter=matter, template=template,
        template_version=template.version, snapshot=snapshot, created_by=actor,
        task_due_date=task_due_date if template.tasks else None, task_ids=task_ids)
    for kind, lines in (("check", template.checklist), ("document", template.documents)):
        for title in lines:
            MatterChecklist.objects.create(organization=organization, matter=matter, application=application,
                title=title, kind=kind, created_by=actor)
    audit(organization=organization, actor=actor, action="routine.applied", obj=matter,
          description=f"Rotina {template.title}, versão {template.version}, aplicada: {len(task_ids)} tarefas e {len(template.checklist) + len(template.documents)} conferências. Aplicação #{application.pk}.")
    return application, True


@transaction.atomic
def add_checklist(*, actor, matter, title, kind="check"):
    matter = Matter.objects.select_for_update().get(pk=matter.pk, organization_id=matter.organization_id)
    _authorize_write(actor=actor, obj=matter)
    item = MatterChecklist.objects.create(organization=matter.organization, matter=matter, title=title.strip(), kind=kind, created_by=actor)
    audit(organization=matter.organization, actor=actor, action="routine.check_added", obj=matter,
          description=f"Conferência adicionada: {item.title}. Item #{item.pk}.")
    return item


@transaction.atomic
def set_checklist_status(*, actor, item, done, note, expected_version):
    item = MatterChecklist.objects.select_for_update().select_related("organization").get(pk=item.pk, organization_id=item.organization_id)
    _authorize_write(actor=actor, obj=item)
    if item.version != expected_version:
        raise ValidationError("Este item foi alterado por outra pessoa. Atualize a página.")
    if type(done) is not bool:
        raise ValidationError("Escolha uma situação válida.")
    if done == item.done:
        return item
    if not note.strip():
        raise ValidationError("Registre a evidência de conferência ou o motivo da reabertura.")
    if len(note) > 1000:
        raise ValidationError("Use até 1000 caracteres na observação.")
    item._allow_transition = True
    item.done = done
    item.version += 1
    item.completed_at = timezone.now() if done else None
    item.completed_by = actor if done else None
    item.completion_note = note.strip() if done else ""
    item.save()
    audit(organization=item.organization, actor=actor, action="routine.check_done" if done else "routine.check_reopened", obj=item.matter,
          description=f"{item.title}: {'conferido' if done else 'reaberto'}. {note.strip()} (item #{item.pk})")
    return item


@transaction.atomic
def add_comment(*, actor, matter, body):
    matter = Matter.objects.select_for_update().get(pk=matter.pk, organization_id=matter.organization_id)
    _authorize_write(actor=actor, obj=matter)
    comment = MatterComment.objects.create(organization=matter.organization, matter=matter, body=body.strip(), created_by=actor)
    audit(organization=matter.organization, actor=actor, action="routine.comment_added", obj=matter,
          description=f"Comentário interno registrado. Comentário #{comment.pk}.")
    return comment


def matter_context(user, organization, matter):
    if not visible_matters(user, organization).filter(pk=matter.pk).exists():
        raise PermissionDenied("Você não tem acesso à pasta.")
    items = MatterChecklist.objects.filter(organization=organization, matter=matter).select_related("created_by", "completed_by")
    totals = items.aggregate(total=Count("pk"), done=Count("pk", filter=Q(done=True)))
    return {"routine_items": items, "routine_total": totals["total"], "routine_done": totals["done"],
        "routine_percent": round(totals["done"] / totals["total"] * 100) if totals["total"] else 0,
        "routine_comments": MatterComment.objects.filter(organization=organization, matter=matter).select_related("created_by")[:30],
        "routine_applications": RoutineApplication.objects.filter(organization=organization, matter=matter).select_related("created_by"),
        "routine_can_write": can_write(user, organization)}


def dashboard_routines(user, organization, limit=4, niche=""):
    items = visible_records(user, organization, MatterChecklist).filter(done=False).select_related("matter")
    if niche:
        items = items.filter(matter__area__in=practice_area_values(niche))
    return {"routine_pending_count": items.count(), "routine_pending": items[:limit]}
