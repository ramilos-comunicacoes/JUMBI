import uuid
from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.legal.models import Contact, Matter
from apps.legal.services import visible_matters
from .models import FeePlan
from .services import build_schedule


class FeePlanForm(forms.Form):
    operation_key = forms.UUIDField(widget=forms.HiddenInput)
    title = forms.CharField(label="Descrição do acordo", max_length=180)
    matter = forms.ModelChoiceField(label="Pasta jurídica", queryset=Matter.objects.none())
    client = forms.ModelChoiceField(label="Cliente", queryset=Contact.objects.none())
    kind = forms.ChoiceField(label="Modalidade", choices=FeePlan.Kind.choices)
    amount = forms.DecimalField(label="Valor (R$)", max_digits=14, decimal_places=2, min_value=Decimal("0.01"), widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}), help_text="Parcelado: valor total do acordo. Assessoria mensal: valor de cada mês.")
    periods = forms.IntegerField(label="Quantidade de meses", min_value=1, max_value=36, initial=6)
    first_due_date = forms.DateField(label="Primeiro vencimento", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), initial=timezone.localdate)
    notes = forms.CharField(label="Condições do acordo", max_length=3000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    reviewed = forms.BooleanField(label="Conferi o cliente, os valores e as datas deste cronograma.", required=False)

    def __init__(self, *args, actor, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["operation_key"].initial = uuid.uuid4()
        self.fields["matter"].queryset = visible_matters(actor, organization).select_related("client")
        self.fields["client"].queryset = Contact.objects.filter(organization=organization)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
                field.widget.attrs["class"] = "form-control"

    def clean(self):
        data = super().clean()
        if all(name in data for name in ("kind", "amount", "periods", "first_due_date")):
            self.schedule = build_schedule(**{name: data[name] for name in ("kind", "amount", "periods", "first_due_date")})
        matter, client = data.get("matter"), data.get("client")
        if matter and client and matter.client_id and matter.client_id != client.pk:
            self.add_error("client", "Selecione o cliente cadastrado nesta pasta.")
        return data
