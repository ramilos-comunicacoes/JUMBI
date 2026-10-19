from django import forms
from .models import Campaign, Lead, MarketingExpense, LeadStage, MarketingChannel


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = [
            "name", "channel", "objective", "budget", "spent",
            "status", "start_date", "end_date",
            "utm_source", "utm_medium", "utm_campaign", "utm_content",
            "target_audience", "notes"
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "target_audience": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = [
            "name", "phone", "email", "channel", "campaign",
            "legal_area", "stage", "estimated_value", "closed_value",
            "loss_reason", "assigned_to", "notes"
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["campaign"].queryset = Campaign.objects.filter(organization=organization)
            from django.contrib.auth import get_user_model
            User = get_user_model()
            self.fields["assigned_to"].queryset = User.objects.filter(
                memberships__organization=organization,
                memberships__is_active=True
            ).distinct()


class LeadQuickStatusForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ["stage"]


class LeadConvertForm(forms.Form):
    matter_title = forms.CharField(
        label="Título da Nova Pasta Jurídica",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ex: Aposentadoria por Idade Urbana - João"})
    )
    closed_value = forms.DecimalField(
        label="Valor Fechado de Honorários (R$)",
        max_digits=12,
        decimal_places=2,
        required=False,
    )


class MarketingExpenseForm(forms.ModelForm):
    class Meta:
        model = MarketingExpense
        fields = ["title", "category", "campaign", "amount", "date", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["campaign"].queryset = Campaign.objects.filter(organization=organization)
