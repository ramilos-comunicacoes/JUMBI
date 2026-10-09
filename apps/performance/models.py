from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.niches import PRACTICE_AREAS
from apps.legal.models import ImmutableTenantModel, TenantModel


class Goal(TenantModel):
    class Metric(models.TextChoices):
        MANUAL = "manual", "Indicador manual"
        TASKS = "tasks", "Tarefas concluídas"
        MATTERS = "matters", "Pastas abertas no período"
        REVENUE = "revenue", "Receita recebida líquida"

    title = models.CharField("Título", max_length=180)
    description = models.TextField("Descrição", blank=True)
    metric = models.CharField("Indicador", max_length=15, choices=Metric.choices, default=Metric.MANUAL)
    target = models.DecimalField("Objetivo", max_digits=14, decimal_places=2)
    manual_value = models.DecimalField("Progresso informado", max_digits=14, decimal_places=2, default=Decimal("0"))
    starts_on = models.DateField("Início do período")
    ends_on = models.DateField("Fim do período")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True, related_name="performance_goals", verbose_name="Responsável")
    niche = models.CharField("Área de atuação", max_length=40, choices=PRACTICE_AREAS, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_performance_goals")
    archived = models.BooleanField("Arquivada", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ends_on", "pk"]
        constraints = [
            models.CheckConstraint(condition=Q(target__gt=0), name="performance_goal_target_positive"),
            models.CheckConstraint(condition=Q(manual_value__gte=0), name="performance_goal_progress_nonnegative"),
            models.CheckConstraint(condition=Q(ends_on__gte=models.F("starts_on")), name="performance_goal_valid_period"),
        ]
        indexes = [models.Index(fields=["organization", "archived", "ends_on"], name="performance_goal_period_idx")]

    def clean(self):
        super().clean()
        errors = {}
        if not self.title.strip():
            errors["title"] = "Informe um título para a meta."
        if self.target is not None and self.target <= 0:
            errors["target"] = "O objetivo deve ser maior que zero."
        if self.target is not None and self.metric in {self.Metric.TASKS, self.Metric.MATTERS} and self.target != self.target.to_integral_value():
            errors["target"] = "Use um número inteiro para este indicador."
        if self.manual_value is not None and self.manual_value < 0:
            errors["manual_value"] = "O progresso não pode ser negativo."
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            errors["ends_on"] = "O fim do período deve ser igual ou posterior ao início."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class GoalUpdate(ImmutableTenantModel):
    goal = models.ForeignKey(Goal, on_delete=models.PROTECT, related_name="updates")
    previous_value = models.DecimalField(max_digits=14, decimal_places=2)
    value = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.TextField("Evidência / observação")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="performance_updates")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def clean(self):
        super().clean()
        if not self.note.strip():
            raise ValidationError({"note": "Registre uma evidência ou observação do progresso."})
        if self.value is not None and self.value < 0:
            raise ValidationError({"value": "O progresso não pode ser negativo."})
