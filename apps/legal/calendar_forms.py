import re
from datetime import date

from django import forms


class CalendarFilterForm(forms.Form):
    month = forms.CharField(required=False, max_length=7)
    day = forms.DateField(required=False)
    kind = forms.ChoiceField(required=False, choices=[
        ("", "Tudo"), ("deadline", "Prazos"), ("task", "Tarefas"),
        ("appointment", "Compromissos"), ("important", "Datas importantes"),
    ])

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
