from decimal import Decimal
import uuid

from django import forms
from django.contrib.auth import get_user_model

from apps.core.models import Membership
from .models import (
    Appointment, Contact, CourtCase, Deadline, Document, FinanceEntry, Matter,
    Opportunity, Payment, Task,
)
from .services import visible_matters


def accessible_matters(organization, user):
    return visible_matters(user, organization)


class OrganizationModelForm(forms.ModelForm):
    def __init__(self, *args, organization, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.user = user
        self.instance.organization = organization
        active_user_ids = Membership.objects.filter(
            organization=organization, is_active=True
        ).values_list("user_id", flat=True)
        for name in ("owner", "members"):
            if name in self.fields:
                self.fields[name].queryset = get_user_model().objects.filter(
                    pk__in=active_user_ids, is_active=True
                ).order_by("first_name", "email")
                if name == 'owner':
                    self.fields[name].queryset = get_user_model().objects.filter(
                        pk__in=Membership.objects.filter(organization=organization, is_active=True)
                        .exclude(role='client').values('user_id'), is_active=True).order_by('first_name', 'email')
        if "matter" in self.fields:
            self.fields["matter"].queryset = accessible_matters(organization, user).order_by("title")
            if self.instance.pk:
                self.fields["matter"].disabled = True
                self.fields["matter"].help_text = "A pasta de um registro existente é preservada para manter seu contexto e histórico."
        for name in ("client", "contact"):
            if name in self.fields:
                self.fields[name].queryset = Contact.objects.filter(
                    organization=organization
                ).order_by("name")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class ContactForm(OrganizationModelForm):
    class Meta:
        model = Contact
        fields = ("name", "kind", "document", "email", "phone", "birth_date")
        labels = {"name": "Nome / razão social", "kind": "Tipo de pessoa", "document": "CPF / CNPJ", "email": "E-mail", "phone": "Telefone"}
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        help_texts = {"birth_date": "Opcional, somente pessoa física. Os lembretes aparecem para clientes vinculados a uma pasta acessível."}


class MatterForm(OrganizationModelForm):
    class Meta:
        model = Matter
        fields = ("title", "client", "nature", "area", "status", "description", "owner", "confidential", "members")
        labels = {"title": "Título da pasta", "client": "Cliente", "nature": "Natureza", "area": "Área jurídica", "status": "Situação", "description": "Descrição", "owner": "Responsável", "confidential": "Pasta sigilosa", "members": "Pessoas autorizadas"}
        widgets = {"description": forms.Textarea(attrs={"rows": 4}), "members": forms.CheckboxSelectMultiple()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.core.niches import PRACTICE_AREAS, practice_area_choices
        configured = practice_area_choices(self.organization)
        choices = list(configured or PRACTICE_AREAS)
        previous = self.instance.area if self.instance.pk else ""
        if previous and previous not in dict(choices):
            choices.append((previous, previous + " (registro existente)"))
        self.fields["area"] = forms.ChoiceField(label="Nicho / área jurídica", required=False,
            choices=[("", "Selecione a área"), *choices], help_text="Áreas de atuação configuradas pela administração. Cada pasta pode pertencer a um nicho do escritório.")
        role = Membership.objects.filter(organization=self.organization, user=self.user, is_active=True).values_list("role", flat=True).first()
        if role not in {"owner", "manager"}:
            for field in ("owner", "confidential", "members"):
                self.fields.pop(field, None)
            if not self.instance.pk:
                self.instance.owner = self.user

    def clean(self):
        data = super().clean()
        if "confidential" in self.fields and data.get("confidential"):
            permitted_ids = {u.pk for u in data.get("members", [])}
            owner = data.get("owner")
            if owner:
                permitted_ids.add(owner.pk)
            if self.user.pk not in permitted_ids:
                self.add_error("members", "Mantenha seu usuário como responsável ou entre as pessoas autorizadas à pasta sigilosa.")
        return data


class CourtCaseForm(OrganizationModelForm):
    class Meta:
        model = CourtCase
        fields = ("matter", "number", "court", "opposing_party", "notes")
        labels = {"matter": "Pasta", "number": "Número CNJ / administrativo", "court": "Tribunal / órgão", "opposing_party": "Parte contrária", "notes": "Observações"}
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}


class TaskForm(OrganizationModelForm):
    class Meta:
        model = Task
        fields = ("matter", "title", "description", "owner", "due_date", "priority")
        labels = {"matter": "Pasta", "title": "Tarefa", "description": "Descrição", "owner": "Responsável", "due_date": "Entrega interna", "priority": "Prioridade"}
        widgets = {"description": forms.Textarea(attrs={"rows": 4}), "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].required = True


class DeadlineForm(OrganizationModelForm):
    change_reason = forms.CharField(label="Motivo da alteração do vencimento", required=False, widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)

    class Meta:
        model = Deadline
        fields = ("matter", "title", "source", "due_date", "owner")
        labels = {"matter": "Pasta", "title": "Obrigação jurídica", "source": "Fonte e referência da comunicação", "due_date": "Vencimento informado", "owner": "Responsável"}
        widgets = {"source": forms.Textarea(attrs={"rows": 3}), "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_due_date = self.instance.due_date if self.instance.pk else None
        self.fields["owner"].required = True
        self.fields["source"].required = True
        if not self.instance.pk:
            self.fields.pop("change_reason")
        else:
            self.fields["source"].disabled = True
            self.fields["source"].help_text = "A fonte original é preservada. Uma comunicação diferente deve gerar outra obrigação."
            if self.instance.status != Deadline.Status.PENDING:
                self.fields["title"].disabled = True
            if self.instance.status == Deadline.Status.FULFILLED:
                self.fields["owner"].disabled = True
                self.fields["due_date"].disabled = True
                self.fields.pop("change_reason")

    def clean(self):
        data = super().clean()
        if self.instance.pk and data.get("due_date") != self.original_due_date and not data.get("change_reason", "").strip():
            self.add_error("change_reason", "Explique o motivo da mudança. O vencimento anterior será preservado no histórico.")
        return data

    def _post_clean(self):
        # Validate the proposed date, but persist its transition only through
        # revise_deadline, which records the old value and invalidates review.
        self.instance._allow_transition = True
        try:
            super()._post_clean()
        finally:
            self.instance._allow_transition = False


class AppointmentForm(OrganizationModelForm):
    class Meta:
        model = Appointment
        fields = ("matter", "title", "kind", "starts_at", "ends_at", "location", "owner")
        labels = {"matter": "Pasta", "title": "Compromisso", "starts_at": "Início", "ends_at": "Término", "location": "Local / link", "owner": "Responsável"}
        widgets = {"starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def clean(self):
        data = super().clean()
        if data.get("starts_at") and data.get("ends_at") and data["ends_at"] <= data["starts_at"]:
            self.add_error("ends_at", "O término deve ocorrer depois do início.")
        return data


class DocumentForm(OrganizationModelForm):
    file = forms.FileField(label="Arquivo privado", help_text="Até 15 MB. O arquivo ficará acessível somente às pessoas autorizadas à pasta.")

    class Meta:
        model = Document
        fields = ("matter", "title", "kind")
        labels = {"matter": "Pasta", "title": "Nome do documento", "kind": "Classificação"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.instance.created_by = self.user
        if self.instance.pk:
            self.fields.pop("file")


class FinanceEntryForm(OrganizationModelForm):
    class Meta:
        model = FinanceEntry
        fields = ("matter", "description", "kind", "amount", "due_date")
        labels = {"matter": "Pasta", "description": "Descrição", "kind": "Tipo", "amount": "Valor previsto (R$)", "due_date": "Vencimento"}
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean_amount(self):
        value = self.cleaned_data["amount"]
        if value <= Decimal("0"):
            raise forms.ValidationError("Informe um valor maior que zero.")
        return value


class OpportunityForm(OrganizationModelForm):
    class Meta:
        model = Opportunity
        fields = ("contact", "title", "stage", "amount", "owner", "next_action", "lost_reason")
        labels = {"contact": "Pessoa", "title": "Oportunidade", "stage": "Etapa", "amount": "Valor estimado (R$)", "owner": "Responsável", "next_action": "Próxima ação", "lost_reason": "Motivo da perda"}
        widgets = {"next_action": forms.Textarea(attrs={"rows": 3}), "lost_reason": forms.Textarea(attrs={"rows": 3})}


class TaskCompletionForm(forms.Form):
    evidence = forms.CharField(label="Evidência de conclusão", widget=forms.Textarea(attrs={"rows": 4}), max_length=4000, help_text="Descreva o que foi entregue. A conclusão da tarefa não encerra um prazo jurídico.")


class ReasonForm(forms.Form):
    reason = forms.CharField(label="Motivo", widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)


class DeadlineConfirmationForm(forms.Form):
    checked = forms.BooleanField(label="Conferi a fonte, a obrigação, o responsável e o vencimento informado.", required=True)


class DeadlineFulfillmentForm(forms.Form):
    evidence = forms.CharField(label="Evidência do cumprimento", widget=forms.Textarea(attrs={"rows": 4}), max_length=4000, help_text="Informe a referência do protocolo ou comprovante conferido. Anexe o documento à pasta quando aplicável.")


class PaymentForm(forms.Form):
    operation_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    amount = forms.DecimalField(label="Valor da baixa (R$)", min_value=Decimal("0.01"), max_digits=14, decimal_places=2)
    date = forms.DateField(label="Data da movimentação", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    note = forms.CharField(label="Comprovante / observação", widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)


class PaymentReversalForm(forms.Form):
    payment = forms.ModelChoiceField(label="Baixa a estornar", queryset=Payment.objects.none())
    reason = forms.CharField(label="Motivo do estorno", widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)


class DocumentUploadForm(forms.Form):
    file = forms.FileField(label="Nova versão do arquivo", help_text="A versão anterior será preservada. Até 15 MB.")


MODULE_FORMS = {
    "contacts": ContactForm, "matters": MatterForm, "cases": CourtCaseForm,
    "tasks": TaskForm, "deadlines": DeadlineForm, "appointments": AppointmentForm,
    "documents": DocumentForm, "finance": FinanceEntryForm, "crm": OpportunityForm,
}
