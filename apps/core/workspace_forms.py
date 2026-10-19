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


from apps.core.models import OrganizationRole
from apps.core.services import AVAILABLE_MODULE_PERMISSIONS


class InvitationForm(forms.Form):
    email = forms.EmailField(label="E-mail da pessoa convidada")
    role = forms.ChoiceField(
        label="Perfil de autoridade",
        choices=[("operator", "Operação"), ("viewer", "Somente consulta"), ("manager", "Gestão"), ("client", "Cliente · somente portal")],
    )
    position = forms.ModelChoiceField(
        label="Cargo na hierarquia",
        queryset=OrganizationRole.objects.none(),
        required=False,
        empty_label="Selecione um cargo (opcional)",
    )
    permissions = forms.MultipleChoiceField(
        label="Módulos liberados",
        choices=AVAILABLE_MODULE_PERMISSIONS,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Marque os módulos específicos que esta pessoa poderá acessar. Se nenhum for marcado, todos os módulos permitidos pelo perfil serão liberados.",
    )

    def __init__(self, *args, membership=None, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if membership and membership.role == "owner":
            self.fields["role"].choices += [("owner", "Direção")]
        if organization:
            from apps.core.team import ensure_default_roles
            ensure_default_roles(organization)
            self.fields["position"].queryset = OrganizationRole.objects.filter(organization=organization, is_active=True).order_by("hierarchy_level", "name")

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class MemberEditForm(forms.Form):
    role = forms.ChoiceField(
        label="Perfil de autoridade",
        choices=[("operator", "Operação"), ("viewer", "Somente consulta"), ("manager", "Gestão"), ("client", "Cliente · somente portal")],
    )
    position = forms.ModelChoiceField(
        label="Cargo na hierarquia",
        queryset=OrganizationRole.objects.none(),
        required=False,
        empty_label="Selecione um cargo (opcional)",
    )
    permissions = forms.MultipleChoiceField(
        label="Módulos liberados",
        choices=AVAILABLE_MODULE_PERMISSIONS,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Marque os módulos específicos que esta pessoa poderá acessar. Se nenhum for marcado, todos os módulos permitidos pelo perfil serão liberados.",
    )
    is_active = forms.BooleanField(label="Acesso ativo no escritório", required=False)

    def __init__(self, *args, target_member=None, actor_membership=None, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if actor_membership and actor_membership.role == "owner":
            self.fields["role"].choices += [("owner", "Direção")]
        if organization:
            from apps.core.team import ensure_default_roles
            ensure_default_roles(organization)
            self.fields["position"].queryset = OrganizationRole.objects.filter(organization=organization, is_active=True).order_by("hierarchy_level", "name")
        if target_member:
            self.target_member = target_member
            self.initial.setdefault("role", target_member.role)
            self.initial.setdefault("position", target_member.position_id)
            self.initial.setdefault("permissions", target_member.permissions or [])
            self.initial.setdefault("is_active", target_member.is_active)


class ResetSystemForm(forms.Form):
    password = forms.CharField(
        label="Sua senha de administrador",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "Digite sua senha para confirmar"}),
        help_text="Por segurança, digite a senha da sua conta de administrador para autorizar o reset.",
    )
    confirmation_text = forms.CharField(
        label="Digite a palavra RESETAR para confirmar",
        max_length=20,
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": "RESETAR"}),
        help_text="Digite exatamente a palavra RESETAR em maiúsculas.",
    )
    confirm_checkbox = forms.BooleanField(
        label="Estou ciente de que todos os dados operacionais (clientes, pastas, tarefas, prazos e documentos) serão excluídos permanentemente.",
        required=True,
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not self.user or not self.user.check_password(password):
            raise ValidationError("Senha incorreta. O reset não foi autorizado.")
        return password

    def clean_confirmation_text(self):
        text = self.cleaned_data.get("confirmation_text", "").strip().upper()
        if text != "RESETAR":
            raise ValidationError("Digite exatamente a palavra RESETAR.")
        return text


class InvitationAcceptForm(UserCreationForm):
    first_name = forms.CharField(label="Seu nome", max_length=150)

    class Meta:
        model = get_user_model()
        fields = ["first_name", "password1", "password2"]

