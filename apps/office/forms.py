from django import forms

from .models import (
    Client,
    LegalCase,
    LegalDocument,
    MatterType,
    OfficeFinanceEntry,
    OfficePurchase,
    PracticeArea,
    StaffMember,
    WorkItem,
)


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ("name", "email", "phone")
        labels = {"name": "Nome / razão social", "email": "E-mail", "phone": "Telefone"}


class WorkItemForm(forms.ModelForm):
    class Meta:
        model = WorkItem
        fields = ("title", "case", "client", "kind", "priority", "status", "due_date")
        labels = {
            "title": "Atividade / prazo",
            "case": "Processo / caso",
            "client": "Cliente",
            "kind": "Tipo",
            "priority": "Prioridade",
            "status": "Situação",
            "due_date": "Data limite",
        }
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, organization, case_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(organization=organization)
        self.fields["case"].queryset = (
            case_queryset if case_queryset is not None else LegalCase.objects.filter(organization=organization)
        )
        self.fields["kind"].required = False
        self.fields["priority"].required = False

    def clean(self):
        cleaned_data = super().clean()
        legal_case = cleaned_data.get("case")
        client = cleaned_data.get("client")
        if legal_case and client and legal_case.client_id and legal_case.client_id != client.id:
            self.add_error("client", "O cliente deve ser o mesmo vinculado ao processo selecionado.")
        if legal_case and not client:
            cleaned_data["client"] = legal_case.client
        return cleaned_data


class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = StaffMember
        fields = ("name", "role", "email", "phone")
        labels = {"name": "Nome completo", "role": "Função", "email": "E-mail", "phone": "Telefone"}


class LegalCaseForm(forms.ModelForm):
    create_initial_checklist = forms.BooleanField(
        required=False,
        initial=True,
        label="Criar checklist inicial sugerido",
        help_text="Adiciona à agenda as etapas internas do tipo de caso selecionado.",
    )

    class Meta:
        model = LegalCase
        fields = (
            "client",
            "title",
            "practice_area",
            "matter_type",
            "nature",
            "stage",
            "priority",
            "case_number",
            "court",
            "opposing_party",
            "responsible",
            "next_deadline",
            "confidential",
            "description",
            "status",
            "create_initial_checklist",
        )
        labels = {
            "client": "Cliente",
            "title": "Título do caso",
            "practice_area": "Área jurídica",
            "matter_type": "Tipo de demanda",
            "nature": "Natureza",
            "stage": "Fase atual",
            "priority": "Prioridade",
            "case_number": "Número do processo / protocolo",
            "court": "Tribunal / órgão",
            "opposing_party": "Parte contrária / interessado",
            "responsible": "Responsável",
            "next_deadline": "Próximo prazo",
            "confidential": "Caso sigiloso",
            "description": "Resumo e estratégia inicial",
            "status": "Situação",
        }
        widgets = {
            "next_deadline": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, organization, can_mark_confidential=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(organization=organization)
        self.fields["responsible"].queryset = StaffMember.objects.filter(organization=organization, is_active=True)
        self.fields["practice_area"].queryset = PracticeArea.objects.filter(is_active=True)
        self.fields["matter_type"].queryset = MatterType.objects.filter(
            is_active=True,
            practice_area__is_active=True,
        ).select_related("practice_area")
        for field_name in ("nature", "stage", "priority"):
            self.fields[field_name].required = False
        if not can_mark_confidential:
            self.fields.pop("confidential")

    def clean(self):
        cleaned_data = super().clean()
        practice_area = cleaned_data.get("practice_area")
        matter_type = cleaned_data.get("matter_type")
        if matter_type and practice_area and matter_type.practice_area_id != practice_area.id:
            self.add_error("matter_type", "O tipo de demanda não pertence à área jurídica selecionada.")
        elif matter_type and not practice_area:
            cleaned_data["practice_area"] = matter_type.practice_area
        return cleaned_data


class LegalDocumentForm(forms.ModelForm):
    class Meta:
        model = LegalDocument
        fields = ("case", "client", "title", "document_type", "file")
        labels = {
            "case": "Processo / caso",
            "client": "Cliente",
            "title": "Título do documento",
            "document_type": "Tipo de documento",
            "file": "Arquivo",
        }

    def __init__(self, *args, organization, case_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["case"].queryset = (
            case_queryset if case_queryset is not None else LegalCase.objects.filter(organization=organization)
        )
        self.fields["client"].queryset = Client.objects.filter(organization=organization)


class OfficeFinanceEntryForm(forms.ModelForm):
    class Meta:
        model = OfficeFinanceEntry
        fields = ("client", "case", "kind", "description", "amount", "due_date", "paid")
        labels = {
            "client": "Cliente",
            "case": "Processo / caso",
            "kind": "Tipo",
            "description": "Descrição",
            "amount": "Valor",
            "due_date": "Vencimento",
            "paid": "Pago / recebido",
        }
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, organization, case_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(organization=organization)
        self.fields["case"].queryset = (
            case_queryset if case_queryset is not None else LegalCase.objects.filter(organization=organization)
        )


class OfficePurchaseForm(forms.ModelForm):
    class Meta:
        model = OfficePurchase
        fields = ("supplier_name", "item", "amount", "purchased_at", "paid")
        labels = {
            "supplier_name": "Fornecedor",
            "item": "Item / serviço",
            "amount": "Valor",
            "purchased_at": "Data da compra",
            "paid": "Pago",
        }
        widgets = {"purchased_at": forms.DateInput(attrs={"type": "date"})}
