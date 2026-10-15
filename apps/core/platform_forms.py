from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.billing.models import OrganizationSubscription
from apps.billing.plans import PLAN_CHOICES
from .models import Organization, User
from .niches import PRACTICE_AREAS


class OfficeConfigurationForm(forms.ModelForm):
    practice_areas = forms.MultipleChoiceField(
        label="Áreas de atuação", choices=PRACTICE_AREAS, widget=forms.CheckboxSelectMultiple,
        help_text="Selecione uma ou várias áreas. Elas podem ser combinadas, sem limite de seleção.",
    )

    class Meta:
        model = Organization
        fields = ("name", "contact_email", "contact_phone", "practice_areas")
        labels = {"name": "Nome do escritório", "contact_email": "E-mail do escritório", "contact_phone": "Telefone do escritório"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.CheckboxSelectMultiple, forms.CheckboxInput)):
                field.widget.attrs.setdefault("class", "form-control")


class OfficeCreationForm(OfficeConfigurationForm):
    is_partner = forms.BooleanField(label="Parceiro — gratuito e ilimitado", required=False,
        help_text="Ativa o acesso completo do Max, sem cobrança, vencimento ou limites comerciais. Somente o superusuário concede essa condição.")
    owner_name = forms.CharField(label="Nome do responsável", max_length=150)
    owner_email = forms.EmailField(label="E-mail de acesso do responsável")
    password = forms.CharField(label="Senha inicial", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password_confirmation = forms.CharField(label="Confirme a senha", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    plan = forms.ChoiceField(label="Plano", choices=PLAN_CHOICES)
    subscription_status = forms.ChoiceField(label="Situação da assinatura", choices=OrganizationSubscription.Status.choices, initial="pending")

    def clean_owner_email(self):
        email = self.cleaned_data["owner_email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Já existe uma conta com este e-mail. Utilize outro e-mail para criar um novo escritório.")
        return email

    def clean(self):
        data = super().clean()
        password = data.get("password")
        if password and password != data.get("password_confirmation"):
            self.add_error("password_confirmation", "As senhas não conferem.")
        if password:
            user = User(email=data.get("owner_email", ""), first_name=data.get("owner_name", ""))
            try:
                validate_password(password, user)
            except ValidationError as exc:
                self.add_error("password", exc)
        return data


class OfficeAccessForm(forms.Form):
    is_partner = forms.BooleanField(label="Parceiro — gratuito e ilimitado", required=False,
        help_text="Todos os recursos do Max, sem cobrança e sem limites comerciais de usuários, pastas e documentos. A opção vale apenas para este escritório.")
    plan = forms.ChoiceField(label="Plano comercial", choices=PLAN_CHOICES,
        help_text="Aplicado quando a condição de parceiro estiver desmarcada.")
    status = forms.ChoiceField(label="Situação do acesso", choices=[("active", "Ativo"), ("suspended", "Suspenso"), ("pending", "Aguardando contratação"), ("demo", "Demonstração")])
    expires_at = forms.DateTimeField(label="Válido até", required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        help_text="Horário de Fortaleza. Parceiros não têm vencimento; a suspensão continua disponível.")
    note = forms.CharField(label="Observação para o histórico", max_length=1000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    revision = forms.CharField(widget=forms.HiddenInput)
