from django import forms
from apps.core.niches import practice_area_choices

KINDS = [
    ("", "Todo o acervo"), ("matters", "Pastas"), ("contacts", "Pessoas"),
    ("cases", "Processos"), ("documents", "Documentos"),
    ("tasks", "Tarefas"), ("deadlines", "Prazos"), ("appointments", "Agenda"),
]


class SearchForm(forms.Form):
    q = forms.CharField(label="O que você procura?", min_length=2, max_length=120,
        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Nome, processo, pasta ou documento…", "autocomplete": "off"}))
    kind = forms.ChoiceField(label="Onde buscar", choices=KINDS, required=False)
    niche = forms.ChoiceField(label="Nicho", required=False)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["niche"].choices = [("", "Todos os nichos")] + list(practice_area_choices(organization))

    def clean_q(self):
        query = " ".join(self.cleaned_data["q"].split())
        if len(query.split()) > 8:
            raise forms.ValidationError("Use até oito palavras por busca.")
        return query


class SaveSearchForm(SearchForm):
    name = forms.CharField(label="Nome da busca", max_length=60,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: processos da família Silva"}))
