from django import forms
from django.utils import timezone

from apps.core.niches import practice_area_choices, practice_area_values
from apps.legal.services import visible_matters
from .models import MatterChecklist, validate_lines


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class TemplateForm(StyledForm):
    title = forms.CharField(label="Nome da rotina", max_length=180)
    description = forms.CharField(label="Orientação da equipe", required=False, max_length=3000, widget=forms.Textarea(attrs={"rows": 3}))
    niches = forms.MultipleChoiceField(label="Áreas de atuação", required=False, widget=forms.CheckboxSelectMultiple,
        help_text="Combine quantas áreas precisar. Sem seleção, o modelo pode ser usado em qualquer pasta.")
    tasks = forms.CharField(label="Tarefas", required=False, max_length=10000, widget=forms.Textarea(attrs={"rows": 5}), help_text="Uma tarefa por linha. A data operacional será escolhida ao aplicar a rotina.")
    checklist = forms.CharField(label="Conferências da equipe", required=False, max_length=10000, widget=forms.Textarea(attrs={"rows": 5}), help_text="Um item por linha.")
    documents = forms.CharField(label="Documentos a solicitar", required=False, max_length=10000, widget=forms.Textarea(attrs={"rows": 5}), help_text="Um documento por linha. Os arquivos devem ser adicionados à pasta separadamente.")
    is_active = forms.BooleanField(label="Disponível para novas aplicações", required=False, initial=True)
    expected_version = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["niches"].choices = practice_area_choices(organization)

    def clean(self):
        data = super().clean()
        for name in ("tasks", "checklist", "documents"):
            if name in data:
                lines = [line.strip() for line in data[name].splitlines() if line.strip()]
                try:
                    validate_lines(lines)
                except forms.ValidationError as exc:
                    self.add_error(name, exc)
                else:
                    data[name] = lines
        if not self.errors and not any(data.get(name) for name in ("tasks", "checklist", "documents")):
            self.add_error(None, "Inclua ao menos uma tarefa, conferência ou documento.")
        return data


class ApplyForm(StyledForm):
    matter = forms.ModelChoiceField(label="Pasta jurídica", queryset=None, empty_label="Selecione a pasta")
    task_due_date = forms.DateField(label="Data operacional das tarefas", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Todas as tarefas serão atribuídas a você nesta data. Ajuste responsáveis e datas no Kanban depois. Esta escolha não cria prazos jurídicos.")
    expected_version = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, organization, user, template, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["matter"].queryset = visible_matters(user, organization).exclude(status="closed")
        if template.niches:
            area_values = [value for code in template.niches for value in practice_area_values(code)]
            self.fields["matter"].queryset = self.fields["matter"].queryset.filter(area__in=area_values)
        self.fields["task_due_date"].required = bool(template.tasks)
        self.fields["task_due_date"].widget.attrs["min"] = timezone.localdate().isoformat()
        if not template.tasks:
            self.fields["task_due_date"].widget = forms.HiddenInput()


class ChecklistForm(StyledForm):
    title = forms.CharField(label="Novo item", max_length=240)
    kind = forms.ChoiceField(label="Tipo", choices=MatterChecklist.Kind.choices)


class CheckStatusForm(StyledForm):
    expected_version = forms.IntegerField(widget=forms.HiddenInput)
    done = forms.TypedChoiceField(label="Situação", choices=[("1", "Conferido"), ("0", "Reabrir")], coerce=lambda value: value == "1")
    note = forms.CharField(label="Evidência / motivo", max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))


class CommentForm(StyledForm):
    body = forms.CharField(label="Comentário interno", max_length=3000, widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Visível à equipe com acesso à pasta. Comentários ficam preservados no histórico.")
