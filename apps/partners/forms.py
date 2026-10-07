from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from apps.core.models import User
from apps.office.models import MatterType, PracticeArea

from .models import (
    Partner,
    PartnerCampaign,
    PartnerCategory,
    PartnerMaterial,
    PartnerNetworkSettings,
    PartnerOpportunity,
)
from .services import possible_duplicates, protected_document


class PartnerNetworkSettingsForm(forms.ModelForm):
    compliance_confirmation = forms.BooleanField(
        label="Confirmo que o escritório revisou as regras éticas, legais e de proteção de dados",
        required=False,
        help_text="Obrigatório para habilitar a rede. O Jumbi fornece infraestrutura tecnológica; a política e a operação são responsabilidade do escritório.",
    )

    class Meta:
        model = PartnerNetworkSettings
        fields = (
            "is_enabled",
            "public_name",
            "presentation",
            "acceptance_rules",
            "relationship_policy",
            "privacy_notice_version",
            "financial_policy_enabled",
            "financial_policy",
        )
        widgets = {
            "presentation": forms.Textarea(attrs={"rows": 3}),
            "acceptance_rules": forms.Textarea(attrs={"rows": 3}),
            "relationship_policy": forms.Textarea(attrs={"rows": 3}),
            "financial_policy": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        enabling = cleaned.get("is_enabled")
        accepted = cleaned.get("compliance_confirmation") or self.instance.compliance_acknowledged
        if enabling and not accepted:
            self.add_error(
                "compliance_confirmation",
                "A confirmação de conformidade é obrigatória para habilitar a rede.",
            )
        if cleaned.get("financial_policy_enabled") and not cleaned.get("financial_policy", "").strip():
            self.add_error("financial_policy", "Descreva a base contratual e os controles desta política.")
        return cleaned

    def save_with_actor(self, actor):
        network = super().save(commit=False)
        if self.cleaned_data.get("compliance_confirmation") and not network.compliance_acknowledged:
            network.compliance_acknowledged = True
            network.compliance_acknowledged_by = actor
            network.compliance_acknowledged_at = timezone.now()
        network.save()
        return network


class PartnerCategoryForm(forms.ModelForm):
    class Meta:
        model = PartnerCategory
        fields = ("name", "kind", "description")


class PartnerProvisionForm(forms.Form):
    person_type = forms.ChoiceField(label="Perfil", choices=Partner.PersonType.choices)
    display_name = forms.CharField(label="Nome do parceiro", max_length=160)
    legal_name = forms.CharField(label="Razão social", max_length=180, required=False)
    document_number = forms.CharField(label="CPF/CNPJ", max_length=24, required=False)
    category = forms.ModelChoiceField(label="Categoria", queryset=PartnerCategory.objects.none(), required=False)
    email = forms.EmailField(label="E-mail de acesso")
    phone = forms.CharField(label="Telefone", max_length=30, required=False)
    whatsapp = forms.CharField(label="WhatsApp", max_length=30, required=False)
    city = forms.CharField(label="Cidade", max_length=100, required=False)
    state = forms.CharField(label="UF", max_length=2, required=False)
    origin = forms.CharField(label="Origem do relacionamento", max_length=120, required=False)
    temporary_password = forms.CharField(
        label="Senha temporária",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Mínimo de 12 caracteres. O parceiro deve alterar a senha no primeiro acesso.",
    )

    def __init__(self, *args, organization, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = PartnerCategory.objects.filter(
            organization=organization,
            is_active=True,
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        existing = User.objects.filter(email=email).first()
        if existing:
            raise forms.ValidationError("Já existe uma conta Jumbi com este e-mail. Use um e-mail exclusivo para o portal.")
        return email

    def clean_temporary_password(self):
        password = self.cleaned_data["temporary_password"]
        validate_password(password)
        return password

    def clean_state(self):
        return self.cleaned_data["state"].strip().upper()

    @transaction.atomic
    def save(self, actor):
        email = self.cleaned_data["email"]
        name_parts = self.cleaned_data["display_name"].strip().split(maxsplit=1)
        user = User.objects.create_user(
            email=email,
            password=self.cleaned_data["temporary_password"],
            first_name=name_parts[0],
            last_name=name_parts[1] if len(name_parts) > 1 else "",
        )
        masked, document_hash = protected_document(self.cleaned_data["document_number"])
        return Partner.objects.create(
            organization=self.organization,
            user=user,
            person_type=self.cleaned_data["person_type"],
            display_name=self.cleaned_data["display_name"],
            legal_name=self.cleaned_data["legal_name"],
            document_masked=masked,
            document_hash=document_hash,
            category=self.cleaned_data["category"],
            email=email,
            phone=self.cleaned_data["phone"],
            whatsapp=self.cleaned_data["whatsapp"],
            city=self.cleaned_data["city"],
            state=self.cleaned_data["state"],
            origin=self.cleaned_data["origin"],
        )


class PartnerCampaignForm(forms.ModelForm):
    required_documents_text = forms.CharField(
        label="Documentos orientativos",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Informe um item por linha. Não solicite documentos sigilosos sem necessidade.",
    )

    class Meta:
        model = PartnerCampaign
        fields = (
            "name",
            "practice_area",
            "description",
            "acceptance_criteria",
            "eligible_categories",
            "status",
            "starts_at",
            "ends_at",
            "opportunity_limit",
            "per_partner_limit",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "acceptance_criteria": forms.Textarea(attrs={"rows": 3}),
            "starts_at": forms.DateInput(attrs={"type": "date"}),
            "ends_at": forms.DateInput(attrs={"type": "date"}),
            "eligible_categories": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, organization, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        self.fields["practice_area"].queryset = PracticeArea.objects.filter(is_active=True)
        self.fields["eligible_categories"].queryset = PartnerCategory.objects.filter(
            organization=organization,
            is_active=True,
        )

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        ends_at = cleaned.get("ends_at")
        if starts_at and ends_at and ends_at < starts_at:
            self.add_error("ends_at", "A data final deve ser posterior ao início.")
        if cleaned.get("status") == PartnerCampaign.Status.ACTIVE:
            network = PartnerNetworkSettings.objects.filter(organization=self.organization).first()
            if not network or not network.is_enabled or not network.compliance_acknowledged:
                self.add_error("status", "Habilite a rede e confirme a conformidade antes de ativar campanhas.")
        return cleaned

    def save(self, commit=True):
        campaign = super().save(commit=False)
        campaign.organization = self.organization
        campaign.required_documents = [
            line.strip()
            for line in self.cleaned_data["required_documents_text"].splitlines()
            if line.strip()
        ]
        if commit:
            campaign.save()
            self.save_m2m()
        return campaign


class PartnerMaterialForm(forms.ModelForm):
    class Meta:
        model = PartnerMaterial
        fields = ("campaign", "title", "description", "kind", "url", "is_active")

    def __init__(self, *args, organization, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        self.fields["campaign"].queryset = PartnerCampaign.objects.filter(organization=organization)

    def save(self, commit=True):
        material = super().save(commit=False)
        material.organization = self.organization
        if commit:
            material.save()
        return material


class PartnerOpportunityForm(forms.ModelForm):
    document_number = forms.CharField(label="CPF/CNPJ", max_length=24, required=False)
    consent_confirmed = forms.BooleanField(
        label="Confirmo que a pessoa autorizou o envio destes dados ao escritório",
        help_text="Não registre dados sem ciência da pessoa interessada.",
    )

    class Meta:
        model = PartnerOpportunity
        fields = (
            "campaign",
            "practice_area",
            "matter_type",
            "interested_party_name",
            "email",
            "phone",
            "city",
            "state",
            "description",
            "source",
            "consent_confirmed",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, partner, **kwargs):
        self.partner = partner
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        campaigns = PartnerCampaign.objects.filter(
            organization=partner.organization,
            status=PartnerCampaign.Status.ACTIVE,
        ).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=today),
            Q(ends_at__isnull=True) | Q(ends_at__gte=today),
        ).annotate(
            total_submissions=Count("opportunities", distinct=True),
            partner_submissions=Count(
                "opportunities",
                filter=Q(opportunities__partner=partner),
                distinct=True,
            ),
        ).filter(
            Q(opportunity_limit__isnull=True) | Q(total_submissions__lt=F("opportunity_limit")),
            Q(per_partner_limit__isnull=True) | Q(partner_submissions__lt=F("per_partner_limit")),
        )
        if partner.category_id:
            campaigns = campaigns.filter(
                Q(eligible_categories__isnull=True)
                | Q(eligible_categories=partner.category)
            ).distinct()
        else:
            campaigns = campaigns.filter(eligible_categories__isnull=True)
        self.fields["campaign"].queryset = campaigns
        self.fields["practice_area"].queryset = PracticeArea.objects.filter(is_active=True)
        self.fields["matter_type"].queryset = MatterType.objects.filter(is_active=True)

    def clean_state(self):
        return self.cleaned_data["state"].strip().upper()

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("email") and not cleaned.get("phone"):
            self.add_error("phone", "Informe ao menos um telefone ou e-mail para contato.")
        campaign = cleaned.get("campaign")
        practice_area = cleaned.get("practice_area")
        matter_type = cleaned.get("matter_type")
        if campaign and campaign.organization_id != self.partner.organization_id:
            self.add_error("campaign", "Campanha indisponível para este parceiro.")
        if campaign and campaign.practice_area_id and practice_area and campaign.practice_area_id != practice_area.id:
            self.add_error("practice_area", "A área deve corresponder à campanha selecionada.")
        if matter_type and practice_area and matter_type.practice_area_id != practice_area.id:
            self.add_error("matter_type", "O tipo de demanda não pertence à área selecionada.")
        if matter_type and not practice_area:
            cleaned["practice_area"] = matter_type.practice_area
        return cleaned

    def save_for_partner(self, *, request):
        opportunity = super().save(commit=False)
        opportunity.organization = self.partner.organization
        opportunity.partner = self.partner
        masked, document_hash = protected_document(self.cleaned_data["document_number"])
        opportunity.document_masked = masked
        opportunity.document_hash = document_hash
        opportunity.consent_confirmed = True
        opportunity.consent_version = self.partner.organization.partner_network.privacy_notice_version
        opportunity.consent_at = timezone.now()
        opportunity.consent_ip = request.META.get("REMOTE_ADDR") or None
        duplicate_ids = possible_duplicates(
            organization=self.partner.organization,
            name=opportunity.interested_party_name,
            email=opportunity.email,
            phone=opportunity.phone,
            document_hash=document_hash,
        )
        opportunity.possible_duplicate = bool(duplicate_ids)
        if duplicate_ids:
            opportunity.status = PartnerOpportunity.Status.DUPLICATE
        opportunity.save()
        return opportunity, duplicate_ids


class PartnerProfileForm(forms.ModelForm):
    class Meta:
        model = Partner
        fields = ("phone", "whatsapp", "city", "state", "address")

    def clean_state(self):
        return self.cleaned_data["state"].strip().upper()


class PartnerTermsAcceptanceForm(forms.Form):
    terms = forms.BooleanField(
        label="Li e aceito as regras de relacionamento definidas pelo escritório",
    )
    privacy = forms.BooleanField(
        label="Li o aviso de privacidade e usarei dados pessoais apenas para a finalidade informada",
    )
