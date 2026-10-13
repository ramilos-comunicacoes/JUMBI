from django import forms

from .models import ImportBatch


class UploadForm(forms.Form):
    kind = forms.ChoiceField(label="O que deseja importar?", choices=ImportBatch.Kind.choices)
    file = forms.FileField(label="Planilha CSV ou XLSX", help_text="Até 2 MB e 500 linhas. CSV em UTF-8; XLSX com apenas uma aba preenchida.", widget=forms.FileInput(attrs={"accept": ".csv,.xlsx"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class ConfirmationForm(forms.Form):
    confirmed = forms.BooleanField(label="Conferi todas as linhas e autorizo criar os registros neste escritório.")
