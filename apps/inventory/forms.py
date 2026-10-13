import uuid
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.forms import formset_factory
from django.utils import timezone

from .models import Asset, Category, Movement, Product, StockLot, Supplier


def _style(form):
    for field in form.fields.values():
        if not isinstance(field.widget, (forms.HiddenInput, forms.CheckboxInput)):
            field.widget.attrs["class"] = "form-control"
        if isinstance(field, forms.DecimalField):
            field.widget.attrs.update({"inputmode": "decimal", "step": "0.001" if field.decimal_places == 3 else "0.01", "min": "0"})


class InventoryModelForm(forms.ModelForm):
    def __init__(self, *args, organization, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.organization = organization
        if "category" in self.fields:
            self.fields["category"].queryset = Category.objects.filter(organization=organization)
        _style(self)


class CategoryForm(InventoryModelForm):
    class Meta:
        model = Category
        fields = ["name"]


class SupplierForm(InventoryModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "document", "phone", "email", "is_active"]


class ProductForm(InventoryModelForm):
    class Meta:
        model = Product
        fields = ["code", "name", "category", "unit", "location", "minimum_stock", "is_active"]
        help_texts = {
            "code": "Código exclusivo deste material no escritório, como PAP-001.",
            "unit": "Será preservada depois da primeira movimentação. Informe sempre quantidades nesta unidade.",
            "minimum_stock": "O alerta aparece quando o saldo total é igual ou inferior a este valor.",
            "is_active": "Desative materiais fora de uso. O histórico e os saldos serão preservados.",
        }


class AssetForm(InventoryModelForm):
    reason = forms.CharField(label="Motivo do cadastro ou alteração", max_length=500, widget=forms.Textarea(attrs={"rows": 2}), help_text="Fica registrado no histórico de responsabilidade, localização e situação do bem.")

    class Meta:
        model = Asset
        fields = ["code", "name", "serial_number", "category", "location", "custodian", "acquired_on", "acquisition_value", "status", "notes"]
        widgets = {"acquired_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), "notes": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"code": "Etiqueta única do patrimônio no escritório.", "acquisition_value": "Valor informativo. Não cria despesa ou pagamento no financeiro."}

    def __init__(self, *args, organization, actor=None, **kwargs):
        super().__init__(*args, organization=organization, actor=actor, **kwargs)
        self.fields["custodian"].queryset = get_user_model().objects.filter(is_active=True, memberships__organization=organization, memberships__is_active=True, memberships__role__in=["owner", "manager", "operator", "viewer"]).distinct().order_by("email")


class ScopedForm(forms.Form):
    def __init__(self, *args, organization, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.actor = actor
        if "operation_key" in self.fields:
            self.fields["operation_key"].initial = uuid.uuid4()
        if "product" in self.fields:
            self.fields["product"].queryset = Product.objects.filter(organization=organization, is_active=True)
        if "lot" in self.fields:
            self.fields["lot"].queryset = StockLot.objects.filter(organization=organization, product__is_active=True).select_related("product")
        if "supplier" in self.fields:
            self.fields["supplier"].queryset = Supplier.objects.filter(organization=organization, is_active=True)
        _style(self)


class MovementForm(ScopedForm):
    operation_key = forms.UUIDField(widget=forms.HiddenInput)
    product = forms.ModelChoiceField(label="Material", queryset=Product.objects.none())
    kind = forms.ChoiceField(label="Operação", choices=[choice for choice in Movement.Kind.choices if choice[0] != "reversal"])
    lot = forms.ModelChoiceField(label="Lote existente", queryset=StockLot.objects.none(), required=False, help_text="Obrigatório para consumo, perda ou contagem. A saída será descontada apenas deste lote.")
    lot_code = forms.CharField(label="Código do novo lote", max_length=80, required=False, help_text="Na entrada, selecione um lote existente ou informe o código de um novo lote.")
    expires_on = forms.DateField(label="Validade do novo lote", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    quantity = forms.DecimalField(label="Quantidade", max_digits=12, decimal_places=3, min_value=Decimal("0"), help_text="Entrada, consumo ou perda: quantidade movimentada. Contagem física: saldo total observado no lote, incluindo zero.")
    reason = forms.CharField(label="Motivo", max_length=500, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        if product:
            self.fields["product"].initial = product.pk
            self.fields["lot"].queryset = self.fields["lot"].queryset.filter(product=product)
        elif self.is_bound:
            product_id = self.data.get(self.add_prefix("product"))
            if str(product_id).isdigit():
                self.fields["lot"].queryset = self.fields["lot"].queryset.filter(product_id=product_id)

    def clean(self):
        data = super().clean()
        kind, lot, product = data.get("kind"), data.get("lot"), data.get("product")
        if lot and product and lot.product_id != product.pk:
            self.add_error("lot", "Selecione um lote deste material.")
        if kind == "entry":
            if lot and data.get("lot_code"):
                self.add_error("lot_code", "Selecione um lote existente ou informe um novo código; escolha apenas uma opção.")
            if not lot and not data.get("lot_code"):
                self.add_error("lot_code", "Informe o código do novo lote ou selecione um lote existente.")
        elif kind and not lot:
            self.add_error("lot", "Selecione o lote que será movimentado.")
        if data.get("quantity") == 0 and kind != "count":
            self.add_error("quantity", "Informe uma quantidade maior que zero.")
        return data


class PurchaseForm(ScopedForm):
    operation_key = forms.UUIDField(widget=forms.HiddenInput)
    supplier = forms.ModelChoiceField(label="Fornecedor", queryset=Supplier.objects.none(), required=False)
    reference = forms.CharField(label="Referência / nota fiscal", max_length=100, required=False)
    purchased_on = forms.DateField(label="Data da compra", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    notes = forms.CharField(label="Observações", max_length=3000, required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_purchased_on(self):
        value = self.cleaned_data["purchased_on"]
        if value > timezone.localdate():
            raise forms.ValidationError("A data da compra não pode estar no futuro.")
        return value


class PurchaseItemForm(ScopedForm):
    product = forms.ModelChoiceField(label="Material", queryset=Product.objects.none())
    quantity = forms.DecimalField(label="Quantidade", max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    unit_cost = forms.DecimalField(label="Custo unitário (R$)", max_digits=12, decimal_places=2, min_value=Decimal("0"))
    lot_code = forms.CharField(label="Lote no recebimento", max_length=80)
    expires_on = forms.DateField(label="Validade", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))


class PurchaseItemsBaseFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            data = form.cleaned_data
            if not data or data.get("DELETE"):
                continue
            identity = (data["product"].pk, data["lot_code"])
            if identity in seen:
                raise forms.ValidationError("Agrupe cada material e lote em uma única linha.")
            seen.add(identity)


PurchaseItemFormSet = formset_factory(PurchaseItemForm, formset=PurchaseItemsBaseFormSet, extra=0, min_num=1, validate_min=True, max_num=30, validate_max=True, absolute_max=30, can_delete=True)


class ReasonForm(forms.Form):
    reason = forms.CharField(label="Motivo", max_length=500, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class ReversalForm(ReasonForm):
    operation_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["operation_key"].initial = uuid.uuid4()
