from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.niches import PRACTICE_AREA_LABELS, validate_practice_areas
from apps.legal.models import ImmutableTenantModel, TenantModel


def validate_lines(value):
    if not isinstance(value, list) or len(value) > 40 or any(
        not isinstance(line, str) or not line.strip() or len(line) > 240 for line in value
    ):
        raise ValidationError("Use até 40 itens, com até 240 caracteres por item.")
    if len({line.strip().casefold() for line in value}) != len(value):
        raise ValidationError("Remova os itens repetidos.")


class RoutineTemplate(TenantModel):
    title = models.CharField("Nome da rotina", max_length=180)
    description = models.TextField("Orientação da equipe", blank=True, max_length=3000)
    niches = models.JSONField("Áreas de atuação", default=list, blank=True, validators=[validate_practice_areas])
    tasks = models.JSONField("Tarefas sugeridas", default=list, blank=True, validators=[validate_lines])
    checklist = models.JSONField("Conferências", default=list, blank=True, validators=[validate_lines])
    documents = models.JSONField("Documentos a solicitar", default=list, blank=True, validators=[validate_lines])
    is_active = models.BooleanField("Disponível para novas aplicações", default=True)
    version = models.PositiveIntegerField(default=1, editable=False)
    seed_key = models.CharField(max_length=60, blank=True, null=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="routine_templates")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "seed_key"], name="routines_template_seed_unique")]

    def __str__(self):
        return self.title

    @property
    def niche_labels(self):
        return [PRACTICE_AREA_LABELS.get(code, code) for code in self.niches]

    def clean(self):
        super().clean()
        if not self.title.strip():
            raise ValidationError({"title": "Informe o nome da rotina."})
        if not (self.tasks or self.checklist or self.documents):
            raise ValidationError("Inclua ao menos uma tarefa, conferência ou documento.")
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values("created_by_id", "seed_key").first()
            if original and (original["created_by_id"] != self.created_by_id or original["seed_key"] != self.seed_key):
                raise ValidationError("Preserve a autoria e a origem da rotina.")


class RoutineApplication(ImmutableTenantModel):
    matter = models.ForeignKey("legal.Matter", on_delete=models.PROTECT, related_name="routine_applications")
    template = models.ForeignKey(RoutineTemplate, on_delete=models.PROTECT, related_name="applications")
    template_version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    task_due_date = models.DateField(null=True, blank=True)
    task_ids = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="routine_applications")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["matter", "template"], name="routines_matter_template_unique")]


class MatterChecklist(TenantModel):
    class Kind(models.TextChoices):
        CHECK = "check", "Conferência"
        DOCUMENT = "document", "Documento a solicitar"

    matter = models.ForeignKey("legal.Matter", on_delete=models.PROTECT, related_name="routine_checklist")
    application = models.ForeignKey(RoutineApplication, on_delete=models.PROTECT, null=True, blank=True, related_name="items")
    title = models.CharField("Item", max_length=240)
    kind = models.CharField("Tipo", max_length=12, choices=Kind.choices, default=Kind.CHECK)
    done = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    completion_note = models.CharField(max_length=1000, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="routine_checks_completed")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="routine_checks_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["done", "created_at", "pk"]

    def clean(self):
        super().clean()
        if not self.title.strip():
            raise ValidationError({"title": "Informe o item de conferência."})
        if self.application_id and self.application.matter_id != self.matter_id:
            raise ValidationError("O item e a aplicação precisam estar na mesma pasta.")
        if self.done and not (self.completed_by_id and self.completed_at and self.completion_note.strip()):
            raise ValidationError("Registre a pessoa, a data e a evidência da conferência.")
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values("created_by_id", "application_id", "title", "kind", "done", "version", "completion_note", "completed_at", "completed_by_id").first()
            if previous:
                if any(previous[key] != getattr(self, key) for key in ("created_by_id", "application_id", "title", "kind")):
                    raise ValidationError("Preserve a origem e a descrição do item; registre um novo item para correções.")
                if not getattr(self, "_allow_transition", False) and any(previous[key] != getattr(self, key) for key in ("done", "version", "completion_note", "completed_at", "completed_by_id")):
                    raise ValidationError("Use a ação de conferência para preservar o histórico.")


class MatterComment(ImmutableTenantModel):
    matter = models.ForeignKey("legal.Matter", on_delete=models.PROTECT, related_name="routine_comments")
    body = models.TextField("Comentário", max_length=3000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="routine_comments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def clean(self):
        super().clean()
        if not self.body.strip():
            raise ValidationError({"body": "Escreva o comentário."})
