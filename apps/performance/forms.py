from django import forms
from django.contrib.auth import get_user_model

from apps.billing.services import has_advanced
from apps.core.models import Membership
from apps.core.niches import practice_area_choices
from .models import Goal


class GoalForm(forms.ModelForm):
    class Meta:
        model = Goal
        fields = ("title", "description", "metric", "target", "starts_on", "ends_on", "owner", "niche", "archived")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "starts_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "ends_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "target": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }

    def __init__(self, *args, organization, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.organization = organization
        if not self.instance.pk:
            self.instance.created_by = user
        self.fields["owner"].queryset = get_user_model().objects.filter(is_active=True, memberships__organization=organization, memberships__is_active=True).distinct()
        self.fields["owner"].empty_label = "Todo o escritório"
        self.fields["owner"].help_text = "Nos indicadores automáticos: responsável pela pasta ou tarefa; em receitas, pessoa que registrou a baixa."
        self.fields["niche"].choices = [("", "Todas as áreas")] + practice_area_choices(organization)
        self.fields["metric"].choices = [(code, label) for code, label in Goal.Metric.choices if code != "revenue" or has_advanced(organization)]
        self.fields["target"].help_text = "Use quantidade para tarefas e pastas, reais para receita e a unidade definida na descrição para indicador manual."
        if self.instance.pk:
            self.fields["metric"].disabled = True
            self.fields["metric"].help_text = "O indicador é preservado. Crie outra meta para acompanhar um indicador diferente."
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class ProgressForm(forms.Form):
    value = forms.DecimalField(label="Total alcançado até agora", max_digits=14, decimal_places=2, min_value=0, widget=forms.NumberInput(attrs={"min": "0", "step": "0.01", "class": "form-control"}))
    note = forms.CharField(label="Evidência / observação", max_length=2000, widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}), help_text="Registre a origem deste total. A atualização fica no histórico da meta.")
