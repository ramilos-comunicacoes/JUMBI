from django import forms

from .models import AgroFinanceEntry, AgroPurchase, Farm, FarmOperation, Field, InventoryItem, StaffMember, Supplier


class FarmForm(forms.ModelForm):
    class Meta:
        model = Farm
        fields = ("name", "city", "state", "total_area_hectares")
        labels = {"name": "Nome da fazenda", "city": "Cidade", "state": "UF", "total_area_hectares": "Área total (ha)"}

    def clean_state(self):
        return self.cleaned_data["state"].upper()


class FieldForm(forms.ModelForm):
    class Meta:
        model = Field
        fields = ("farm", "name", "crop", "area_hectares")
        labels = {"farm": "Fazenda", "name": "Nome do talhão", "crop": "Cultura / safra", "area_hectares": "Área (ha)"}

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = Farm.objects.filter(organization=organization)


class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = StaffMember
        fields = ("name", "role", "email", "phone", "farm")
        labels = {"name": "Nome completo", "role": "Função", "email": "E-mail", "phone": "Telefone", "farm": "Fazenda principal"}

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = Farm.objects.filter(organization=organization)


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ("name", "document", "email", "phone")
        labels = {"name": "Nome / razão social", "document": "CNPJ / CPF", "email": "E-mail", "phone": "Telefone"}


class InventoryItemForm(forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = ("name", "category", "unit", "stock", "minimum_stock")
        labels = {"name": "Insumo / item", "category": "Categoria", "unit": "Unidade", "stock": "Estoque atual", "minimum_stock": "Estoque mínimo"}


class FarmOperationForm(forms.ModelForm):
    class Meta:
        model = FarmOperation
        fields = ("farm", "field", "kind", "title", "status", "scheduled_date", "responsible", "notes")
        labels = {
            "farm": "Fazenda",
            "field": "Talhão",
            "kind": "Tipo de operação",
            "title": "Nome da atividade",
            "status": "Situação",
            "scheduled_date": "Data programada",
            "responsible": "Responsável",
            "notes": "Observações",
        }
        widgets = {"scheduled_date": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = Farm.objects.filter(organization=organization)
        self.fields["field"].queryset = Field.objects.filter(farm__organization=organization)
        self.fields["responsible"].queryset = StaffMember.objects.filter(organization=organization, is_active=True)


class AgroFinanceEntryForm(forms.ModelForm):
    class Meta:
        model = AgroFinanceEntry
        fields = ("farm", "field", "kind", "description", "amount", "due_date", "paid")
        labels = {
            "farm": "Fazenda",
            "field": "Talhão",
            "kind": "Tipo",
            "description": "Descrição",
            "amount": "Valor",
            "due_date": "Vencimento",
            "paid": "Pago / recebido",
        }
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farm"].queryset = Farm.objects.filter(organization=organization)
        self.fields["field"].queryset = Field.objects.filter(farm__organization=organization)


class AgroPurchaseForm(forms.ModelForm):
    class Meta:
        model = AgroPurchase
        fields = ("supplier", "item", "description", "quantity", "total_amount", "purchased_at", "paid", "received")
        labels = {
            "supplier": "Fornecedor",
            "item": "Item de estoque",
            "description": "Descrição da compra",
            "quantity": "Quantidade",
            "total_amount": "Valor total",
            "purchased_at": "Data da compra",
            "paid": "Pago",
            "received": "Recebido",
        }
        widgets = {"purchased_at": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(organization=organization)
        self.fields["item"].queryset = InventoryItem.objects.filter(organization=organization)
