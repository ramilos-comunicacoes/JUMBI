from django import forms
from django.core.exceptions import ValidationError

from .forms import OrganizationBrandingForm
from .preferences import CHOICES, DEFAULTS, NAV_CHOICES, WIDGET_CHOICES, office_preferences, validate_preferences


class WorkspaceCustomizationForm(OrganizationBrandingForm):
    theme = forms.ChoiceField(label="Tema padrão", choices=CHOICES["theme"])
    density = forms.ChoiceField(label="Espaçamento", choices=CHOICES["density"])
    text_size = forms.ChoiceField(label="Tamanho do texto", choices=CHOICES["text_size"])
    sidebar_mode = forms.ChoiceField(label="Menu no desktop", choices=CHOICES["sidebar_mode"])
    motion = forms.ChoiceField(label="Movimento", choices=CHOICES["motion"])
    calendar_view = forms.ChoiceField(label="Visão inicial da agenda", choices=CHOICES["calendar_view"])
    dashboard_view = forms.ChoiceField(label="Dashboard inicial", choices=CHOICES["dashboard_view"])
    landing_page = forms.ChoiceField(label="Página após entrar", choices=CHOICES["landing_page"])
    dashboard_widgets = forms.MultipleChoiceField(label="Blocos do dashboard", choices=WIDGET_CHOICES, required=False, widget=forms.CheckboxSelectMultiple)
    hidden_nav = forms.MultipleChoiceField(label="Abas ocultas no menu", choices=NAV_CHOICES, required=False, widget=forms.CheckboxSelectMultiple)
    nav_order = forms.MultipleChoiceField(choices=NAV_CHOICES, required=False, widget=forms.MultipleHiddenInput)
    djen_name = forms.CharField(label="Nome padrão para pesquisa no DJEN", max_length=200, required=False, help_text="Use o nome completo do advogado. A pesquisa é manual e depende da resposta oficial.")
    birthday_message = forms.CharField(label="Mensagem de aniversário", max_length=1200, widget=forms.Textarea(attrs={"rows": 4}), help_text="Use {cliente} e {escritorio}. O WhatsApp abre a mensagem para revisão e envio manual.")
    revision = forms.CharField(widget=forms.HiddenInput)

    class Meta(OrganizationBrandingForm.Meta):
        fields = ("name", "contact_email", "contact_phone", *OrganizationBrandingForm.Meta.fields)
        labels = {"name": "Nome do escritório", "contact_email": "E-mail de contato", "contact_phone": "Telefone de contato"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        prefs = office_preferences(self.instance)
        for name in DEFAULTS:
            self.fields[name].initial = prefs[name]
        self.fields["revision"].initial = self.instance.updated_at.isoformat()
        for name, field in self.fields.items():
            if field.help_text:
                field.widget.attrs["aria-describedby"] = f"id_{name}_help"

    def clean(self):
        cleaned = super().clean()
        if not self.errors:
            try:
                validate_preferences({key: cleaned[key] for key in DEFAULTS})
            except ValidationError as exc:
                self.add_error(None, exc)
        return cleaned

    def save(self, commit=True):
        org = super().save(commit=False)
        org.workspace_preferences = {key: self.cleaned_data[key] for key in DEFAULTS}
        if commit:
            org.save()
        return org

    def field_groups(self):
        groups = [
            ("identity", "Identidade do escritório", "Sua marca em todas as telas do ambiente.", ["name", "system_title", "contact_email", "contact_phone", "brand_logo", "brand_favicon", "brand_collapsed_logo", "brand_primary_color", "brand_accent_color", "brand_sidebar_color"]),
            ("appearance", "Aparência e conforto", "O celular mantém áreas de toque amplas. Reduzir movimento respeita também as preferências do dispositivo.", ["theme", "glassmorphism_intensity", "density", "text_size", "motion", "sidebar_mode"]),
            ("operation", "Sua forma de trabalhar", "Combine áreas de atuação e escolha como começar o dia. Alterar nichos preserva as pastas já cadastradas.", ["practice_areas", "landing_page", "dashboard_view", "calendar_view", "dashboard_widgets"]),
            ("communication", "Comunicação e pesquisas", "Textos próprios do escritório, sempre com revisão antes do envio.", ["djen_name", "birthday_message"]),
            ("navigation", "Um menu com o essencial", "Ocultar uma aba organiza o menu, mas não revoga acesso nem altera o plano. Equipe, segurança e personalização continuam disponíveis.", ["hidden_nav"]),
        ]
        return [{"id": key, "title": title, "description": description, "fields": [self[name] for name in names]} for key, title, description, names in groups]
