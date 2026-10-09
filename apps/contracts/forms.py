import uuid

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.legal.models import Contact
from apps.legal.services import visible_matters
from .catalog import MULTILINE, VARIABLES
from .models import ContractTemplate
from .services import render_body, validate_source


class ContractTemplateForm(forms.ModelForm):
    class Meta:
        model = ContractTemplate
        fields = ["name", "category", "description", "body", "is_active"]
        widgets = {"body": forms.Textarea(attrs={"rows": 24, "data-contract-source": "", "spellcheck": "true"})}


class BuildContractForm(forms.Form):
    operation_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput)
    title = forms.CharField(label="Título do contrato", max_length=220)
    matter = forms.ModelChoiceField(label="Pasta jurídica", queryset=None)
    client = forms.ModelChoiceField(label="Contratante cadastrado", queryset=None)
    source_body = forms.CharField(label="Texto e cláusulas desta versão", max_length=100000, widget=forms.Textarea(attrs={"rows": 22, "data-contract-source": ""}))
    reviewed = forms.BooleanField(label="Conferi os dados e o texto desta versão. Sei que o documento permanece um rascunho para revisão profissional.", required=False)

    def __init__(self, *args, actor, organization, template, contract=None, selected_matter=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["matter"].queryset = visible_matters(actor, organization)
        self.fields["client"].queryset = Contact.objects.filter(organization=organization)
        initial = {"title": template.name, "source_body": template.body}
        values = {
            "escritorio_nome": organization.legal_name or organization.name,
            "escritorio_documento": organization.document,
            "advogado_nome": actor.get_full_name(), "cidade": organization.city,
            "data": timezone.localdate().strftime("%d/%m/%Y"),
        }
        if contract:
            previous = contract.revisions.first()
            initial.update({"title": previous.title, "source_body": previous.source_body, "matter": contract.matter, "client": contract.client})
            values.update(previous.values)
            self.fields["matter"].disabled = True
            self.fields["client"].disabled = True
        elif selected_matter:
            initial["matter"] = selected_matter
            values["pasta_titulo"] = selected_matter.title
            if selected_matter.client_id:
                initial["client"] = selected_matter.client
                for key, attr in [("cliente_nome", "name"), ("cliente_documento", "document"), ("cliente_email", "email"), ("cliente_telefone", "phone")]:
                    values[key] = getattr(selected_matter.client, attr)
        self.initial.update(initial)
        for key, (label, group) in VARIABLES.items():
            widget = forms.Textarea(attrs={"rows": 3}) if key in MULTILINE else forms.TextInput()
            widget.attrs["data-contract-value"] = key
            self.fields["value_" + key] = forms.CharField(label=label, required=False, max_length=8000, widget=widget, initial=values.get(key, ""))
        # Model choice labels are rendered as escaped HTML by Django.
        self.variable_groups = [(group, [self["value_" + key] for key, item in VARIABLES.items() if item[1] == group]) for group in dict.fromkeys(item[1] for item in VARIABLES.values())]

    def clean_source_body(self):
        value = self.cleaned_data["source_body"]
        validate_source(value)
        return value

    def clean(self):
        cleaned = super().clean()
        matter, client = cleaned.get("matter"), cleaned.get("client")
        if matter and client and matter.client_id and matter.client_id != client.pk:
            self.add_error("client", "Selecione o cliente vinculado à pasta.")
        values = {key: cleaned.get("value_" + key, "") for key in VARIABLES}
        if "source_body" in cleaned:
            try:
                cleaned["rendered_text"] = render_body(cleaned["source_body"], values)
            except ValidationError as error:
                self.add_error(None, error)
        cleaned["values"] = values
        return cleaned
