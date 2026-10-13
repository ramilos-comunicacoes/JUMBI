import re
from datetime import date

from django import forms
from django.contrib.auth import get_user_model


CALENDAR_STATUSES = [
    ("all", "Todos os registros"), ("pending", "Em aberto"),
    ("completed", "Concluídos · tarefas e prazos"),
    ("overdue", "Atrasados · tarefas e prazos"),
    ("ended", "Encerrados · compromissos"),
]


class ResponsibleChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return user.get_full_name() or user.email


class CalendarFilterForm(forms.Form):
    view = forms.ChoiceField(label="Visualização", required=False, choices=[("month", "Mês"), ("week", "Semana"), ("day", "Dia")])
    month = forms.CharField(label="Mês", required=False, max_length=7)
    day = forms.DateField(label="Dia", required=False)
    kind = forms.ChoiceField(label="Tipo de registro", required=False, choices=[
        ("", "Tudo"), ("deadline", "Prazos"), ("task", "Tarefas"),
        ("appointment", "Compromissos"), ("important", "Datas importantes"),
    ])
    responsible = ResponsibleChoiceField(label="Responsável", required=False, queryset=get_user_model().objects.none(), empty_label="Toda a equipe")
    status = forms.ChoiceField(label="Situação", required=False, choices=CALENDAR_STATUSES)
    niche = forms.ChoiceField(label="Área de atuação", required=False, choices=[("", "Todos os nichos")])

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        if request is not None:
            from apps.core.models import Membership
            from .niches import niche_selection
            members = Membership.objects.filter(organization=request.organization, is_active=True,
                user__is_active=True, role__in=["owner", "manager", "operator", "viewer"]).values("user_id")
            self.fields["responsible"].queryset = get_user_model().objects.filter(pk__in=members).order_by("first_name", "last_name", "email")
            self.fields["niche"].choices = [("", "Todos os nichos"), *niche_selection(request)[1]]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_status(self):
        return self.cleaned_data.get("status") or "all"

    def clean_month(self):
        value = self.cleaned_data["month"]
        if not value:
            return None
        if not re.fullmatch(r"\d{4}-\d{2}", value):
            raise forms.ValidationError("Use ano e mês no formato AAAA-MM.")
        try:
            result = date.fromisoformat(value + "-01")
        except ValueError:
            raise forms.ValidationError("Mês inválido.") from None
        if not 1901 <= result.year <= 2099:
            raise forms.ValidationError("Escolha um ano entre 1901 e 2099.")
        return result

    def clean_day(self):
        value = self.cleaned_data["day"]
        if value and not 1901 <= value.year <= 2099:
            raise forms.ValidationError("Escolha um ano entre 1901 e 2099.")
        return value
