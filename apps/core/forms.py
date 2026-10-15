from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils.text import slugify

from .models import Membership, Organization, OrganizationRole, User
from .niches import PRACTICE_AREAS, PRACTICE_AREA_LABELS


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}))


class SignUpForm(UserCreationForm):
    organization_name = forms.CharField(label="Nome da empresa", max_length=150)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")

    def clean_email(self):
        return self.cleaned_data["email"].lower()

    @transaction.atomic
    def save(self):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.save()
        base_slug = slugify(self.cleaned_data["organization_name"]) or "organizacao"
        slug = base_slug
        suffix = 2
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        organization = Organization.objects.create(name=self.cleaned_data["organization_name"], slug=slug)
        Membership.objects.create(organization=organization, user=user, role=Membership.Role.OWNER)
        return user


class OrganizationRegistrationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = (
            "name", "legal_name", "document", "business_type", "contact_email",
            "contact_phone", "city", "state", "status",
        )
        widgets = {"state": forms.TextInput(attrs={"maxlength": 2, "style": "text-transform:uppercase"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["business_type"].choices = (
            (Organization.BusinessType.OFFICE, "Jurídico"),
        )
        self.fields["business_type"].initial = Organization.BusinessType.OFFICE
        self.fields["business_type"].widget = forms.HiddenInput()

    def clean_state(self):
        return self.cleaned_data["state"].upper()

    def save(self, commit=True):
        organization = super().save(commit=False)
        base_slug = slugify(organization.name) or "organizacao"
        slug = base_slug
        suffix = 2
        while Organization.objects.filter(slug=slug).exclude(pk=organization.pk).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        organization.slug = slug
        if commit:
            organization.save()
        return organization


class OrganizationBrandingForm(forms.ModelForm):
    practice_areas = forms.MultipleChoiceField(
        label="Áreas de Atuação do Escritório",
        choices=PRACTICE_AREAS,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "practice-area-checkbox"}),
        required=False,
        help_text="Selecione as áreas atendidas pelo escritório para ativar os módulos especializados correspondentes.",
    )

    class Meta:
        model = Organization
        fields = (
            "system_title",
            "brand_logo",
            "brand_favicon",
            "brand_collapsed_logo",
            "glassmorphism_intensity",
            "brand_primary_color",
            "brand_accent_color",
            "brand_sidebar_color",
        )
        widgets = {
            "system_title": forms.TextInput(attrs={"placeholder": "Ex: JUMBI ou Nome do seu Escritório"}),
            "glassmorphism_intensity": forms.Select(),
            "brand_primary_color": forms.TextInput(attrs={"type": "color"}),
            "brand_accent_color": forms.TextInput(attrs={"type": "color"}),
            "brand_sidebar_color": forms.TextInput(attrs={"type": "color"}),
        }
        help_texts = {
            "system_title": "Exibido no topo da barra, nos títulos das páginas e nas notificações.",
            "brand_logo": "PNG, JPG ou WebP, até 2 MB. Fundos uniformes são removidos automaticamente; imagens transparentes são preservadas. O duotone ajusta as cores quando faltar contraste.",
            "brand_favicon": "Favicon da aba do navegador E logo da barra lateral contraída (padrão). Máx. 2 MB.",
            "brand_collapsed_logo": "Opcional: ícone alternativo para o menu recolhido (se não preenchido, usa o favicon).",
            "glassmorphism_intensity": "Estilo visual de transparência e desfoque moderno dos cartões e painéis.",
            "brand_primary_color": "Usada em botões, ícones e seleção ativa de abas.",
            "brand_accent_color": "Usada em gradientes, foco e detalhes de destaque.",
            "brand_sidebar_color": "Base de cor escura da barra lateral e cabeçalho.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["practice_areas"].initial = self.instance.practice_areas or []

    def clean_practice_areas(self):
        areas = self.cleaned_data.get("practice_areas", [])
        return [str(a) for a in areas if str(a) in PRACTICE_AREA_LABELS]

    def save(self, commit=True):
        org = super().save(commit=False)
        if "practice_areas" in self.cleaned_data:
            org.practice_areas = self.cleaned_data["practice_areas"]
        if commit:
            org.save()
        return org

    def _validate_image_file(self, field_name, max_mb=2, allow_ico=False):
        from .image_validation import validated_brand_image
        return validated_brand_image(self.cleaned_data.get(field_name))

    def clean_brand_logo(self):
        return self._validate_image_file("brand_logo", allow_ico=True)

    def clean_brand_favicon(self):
        return self._validate_image_file("brand_favicon", allow_ico=True)

    def clean_brand_collapsed_logo(self):
        return self._validate_image_file("brand_collapsed_logo", allow_ico=True)


class UserAccessProvisionForm(forms.Form):
    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)
    email = forms.EmailField(label="E-mail de acesso")
    organization = forms.ModelChoiceField(label="Organização / sistema", queryset=Organization.objects.none())
    role = forms.ChoiceField(label="Papel no sistema", choices=Membership.Role.choices)
    temporary_password = forms.CharField(
        label="Senha temporária",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Mínimo de 12 caracteres. Entregue por um canal seguro e solicite a troca no primeiro acesso.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organization"].queryset = Organization.objects.filter(
            business_type=Organization.BusinessType.OFFICE,
        ).order_by("name")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Já existe uma conta com este e-mail.")
        return email

    def clean_temporary_password(self):
        password = self.cleaned_data["temporary_password"]
        validate_password(password)
        return password

    @transaction.atomic
    def save(self):
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["temporary_password"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
        )
        Membership.objects.create(
            organization=self.cleaned_data["organization"],
            user=user,
            role=self.cleaned_data["role"],
        )
        return user


class OrganizationRoleForm(forms.ModelForm):
    class Meta:
        model = OrganizationRole
        fields = ("name", "hierarchy_level", "permission_role", "description")
        widgets = {
            "hierarchy_level": forms.NumberInput(attrs={"min": 1, "max": 999}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, organization, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.actor = actor
        if not actor.is_superuser:
            actor_membership = Membership.objects.filter(
                organization=organization,
                user=actor,
                is_active=True,
            ).first()
            if actor_membership and actor_membership.role != Membership.Role.OWNER:
                self.fields["permission_role"].choices = [
                    choice for choice in Membership.Role.choices
                    if choice[0] != Membership.Role.OWNER
                ]

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if OrganizationRole.objects.filter(organization=self.organization, name__iexact=name).exists():
            raise forms.ValidationError("Já existe um cargo com este nome nesta organização.")
        return name

    def save(self, commit=True):
        role = super().save(commit=False)
        role.organization = self.organization
        if commit:
            role.save()
        return role


class OrganizationMemberProvisionForm(forms.Form):
    first_name = forms.CharField(label="Nome", max_length=150)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)
    email = forms.EmailField(label="E-mail pessoal de acesso")
    position = forms.ModelChoiceField(label="Cargo na hierarquia", queryset=OrganizationRole.objects.none())
    reports_to = forms.ModelChoiceField(
        label="Gestor direto",
        queryset=Membership.objects.none(),
        required=False,
        help_text="Opcional. O gestor deve ocupar um nível superior na hierarquia.",
    )
    temporary_password = forms.CharField(
        label="Senha temporária",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Mínimo de 12 caracteres. A pessoa poderá trocar a senha no primeiro acesso.",
    )

    def __init__(self, *args, organization, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.actor = actor
        positions = OrganizationRole.objects.filter(organization=organization, is_active=True)
        if not actor.is_superuser:
            actor_membership = Membership.objects.filter(
                organization=organization,
                user=actor,
                is_active=True,
            ).first()
            if actor_membership and actor_membership.role != Membership.Role.OWNER:
                positions = positions.exclude(permission_role=Membership.Role.OWNER)
        self.fields["position"].queryset = positions
        self.fields["reports_to"].queryset = Membership.objects.filter(
            organization=organization,
            is_active=True,
        ).select_related("user", "position")
        self.fields["reports_to"].label_from_instance = lambda member: (
            f"{member.user.get_full_name() or member.user.email}"
            f" · {member.position.name if member.position else member.get_role_display()}"
        )

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Já existe uma conta com este e-mail. Use um e-mail pessoal diferente.")
        return email

    def clean_temporary_password(self):
        password = self.cleaned_data["temporary_password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        position = cleaned_data.get("position")
        manager = cleaned_data.get("reports_to")
        if position and position.organization_id != self.organization.id:
            self.add_error("position", "Cargo inválido para esta organização.")
        if manager and manager.organization_id != self.organization.id:
            self.add_error("reports_to", "Gestor inválido para esta organização.")
        if manager and manager.position and position:
            if manager.position.hierarchy_level >= position.hierarchy_level:
                self.add_error("reports_to", "O gestor direto deve ocupar um cargo hierarquicamente superior.")
        return cleaned_data

    @transaction.atomic
    def save(self):
        position = self.cleaned_data["position"]
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["temporary_password"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
        )
        membership = Membership.objects.create(
            organization=self.organization,
            user=user,
            role=position.permission_role,
            position=position,
            reports_to=self.cleaned_data.get("reports_to"),
        )
        return membership
