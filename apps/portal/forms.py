from django import forms
from django.contrib.auth import get_user_model

from apps.core.models import Membership
from apps.legal.models import Contact, DocumentVersion
from apps.legal.services import visible_matters
from .models import ClientAccess, ReviewDecision
from .services import authorized_versions


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class AccessForm(StyledForm):
    membership = forms.ModelChoiceField(label="Conta com perfil Cliente", queryset=Membership.objects.none())
    contact = forms.ModelChoiceField(label="Contato representado por esta conta", queryset=Contact.objects.none())
    confirmed = forms.BooleanField(label="Conferi a identidade e autorizo o vínculo desta conta com este contato.")

    def __init__(self, *args, actor, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["membership"].queryset = Membership.objects.filter(organization=organization, role="client", is_active=True, user__is_active=True).select_related("user")
        self.fields["membership"].label_from_instance = lambda item: item.user.email
        self.fields["contact"].queryset = Contact.objects.filter(organization=organization, pk__in=visible_matters(actor, organization).values("client_id"))


class ReviewForm(StyledForm):
    version = forms.ModelChoiceField(label="Versão exata do documento", queryset=DocumentVersion.objects.none())
    reviewer = forms.ModelChoiceField(label="Pessoa revisora (direção ou gestão)", queryset=get_user_model().objects.none())
    note = forms.CharField(label="O que deve ser conferido?", max_length=3000, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, actor, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].queryset = authorized_versions(actor, organization).select_related("document").order_by("document__title", "-number")
        self.fields["version"].label_from_instance = lambda version: f"{version.document.title} · v{version.number} · {version.original_name}"
        self.fields["reviewer"].queryset = get_user_model().objects.filter(memberships__organization=organization, memberships__is_active=True, memberships__role__in=["owner", "manager"], is_active=True).exclude(pk=actor.pk)
        self.fields["reviewer"].help_text = "A revisão exige outra pessoa, com acesso à pasta e diferente de quem enviou a versão."


class DecisionForm(StyledForm):
    outcome = forms.ChoiceField(label="Decisão", choices=ReviewDecision.Outcome.choices)
    note = forms.CharField(label="Justificativa da revisão", max_length=3000, widget=forms.Textarea(attrs={"rows": 4}))
    confirmed = forms.BooleanField(label="Baixei e conferi a versão identificada nesta revisão.")


class PublishForm(StyledForm):
    access = forms.ModelChoiceField(label="Cliente destinatário", queryset=ClientAccess.objects.none())
    title = forms.CharField(label="Título apresentado ao cliente", max_length=240)
    note = forms.CharField(label="Mensagem de apresentação", max_length=3000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    confirmed = forms.BooleanField(label="Autorizo compartilhar esta versão aprovada com o destinatário selecionado.")

    def __init__(self, *args, review, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["access"].queryset = ClientAccess.objects.filter(organization_id=review.organization_id, contact_id=review.version.document.matter.client_id, revoked_at__isnull=True, membership__role="client", membership__is_active=True, membership__user__is_active=True).select_related("contact", "membership__user")


class MessageForm(StyledForm):
    body = forms.CharField(label="Sua mensagem", max_length=3000, widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Escreva sobre este documento…"}))


class RevokeForm(StyledForm):
    reason = forms.CharField(label="Motivo da revogação", max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
