from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "username"}))
    error_messages = {"invalid_login": "E-mail ou senha inválidos. Após muitas tentativas, aguarde 15 minutos.", "inactive": "Esta conta está desativada."}


class SignupForm(UserCreationForm):
    from apps.billing.plans import PLAN_CHOICES
    plan = forms.ChoiceField(label="Seu plano mensal", choices=PLAN_CHOICES)
    organization_name = forms.CharField(label="Nome do escritório", max_length=150)
    first_name = forms.CharField(label="Seu nome", max_length=150)
    email = forms.EmailField(label="E-mail profissional")

    class Meta:
        model = get_user_model()
        fields = ["first_name", "email", "organization_name", "plan", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise ValidationError("Não foi possível criar a conta com este e-mail. Tente entrar com sua conta.")
        return email


class InvitationForm(forms.Form):
    email = forms.EmailField(label="E-mail da pessoa convidada")
    role = forms.ChoiceField(label="Perfil de acesso", choices=[("operator", "Operação"), ("viewer", "Somente consulta"), ("manager", "Gestão")])

    def __init__(self, *args, membership=None, **kwargs):
        super().__init__(*args, **kwargs)
        if membership and membership.role == "owner":
            self.fields["role"].choices += [("owner", "Direção")]

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class InvitationAcceptForm(UserCreationForm):
    first_name = forms.CharField(label="Seu nome", max_length=150)

    class Meta:
        model = get_user_model()
        fields = ["first_name", "password1", "password2"]
