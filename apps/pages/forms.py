from django import forms

from .models import DemoRequest


class DemoRequestForm(forms.ModelForm):
    class Meta:
        model = DemoRequest
        fields = ("name", "work_email", "company", "segment", "message")
        labels = {
            "name": "Seu nome",
            "work_email": "E-mail profissional",
            "company": "Empresa / escritório",
            "segment": "Solução de interesse",
            "message": "Como podemos ajudar?",
        }
        widgets = {"message": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["segment"].choices = (
            (DemoRequest.Segment.LEGAL, "Gestão Jurídica"),
        )
        self.fields["segment"].initial = DemoRequest.Segment.LEGAL
        self.fields["segment"].widget = forms.HiddenInput()
