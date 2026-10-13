from datetime import timedelta
from functools import wraps

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.legal.views import organization_required
from .forms import (AssetForm, CategoryForm, MovementForm, ProductForm, PurchaseForm,
    PurchaseItemFormSet, ReasonForm, ReversalForm, SupplierForm)
from .models import Asset, AssetEvent, Category, Movement, Product, Purchase, StockLot, Supplier
from .services import (cancel_purchase, create_purchase, products_with_stock, receive_purchase,
    record_movement, require_inventory_access, reverse_movement, save_record, stock_summary, visible_records)


def inventory_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require_inventory_access(request.user, request.organization)
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response
    return organization_required(wrapped)


def _context(tab="stock", title="Estoque e inventário", **extra):
    descriptions = {
        "stock": "Controle materiais, lotes, reposição e validades em um só lugar.",
        "purchases": "Registre a compra, confira a entrega e confirme a entrada dos materiais.",
        "movements": "Entradas, saídas e conferências com autor, motivo e saldo de cada lote.",
        "assets": "Bens identificados por etiqueta, com responsável, localização e histórico.",
        "catalog": "Organize as categorias e os fornecedores utilizados pelo escritório.",
    }
    return {"active_nav": "inventory", "inventory_tab": tab, "page_title": title,
        "page_description": descriptions[tab], **extra}


def _records(request, model):
    return visible_records(request.user, request.organization, model)


def _page(request, queryset, size=24):
    query = request.GET.copy()
    query.pop("page", None)
    return {"page": Paginator(queryset, size).get_page(request.GET.get("page")), "query_string": query.urlencode()}


def _error(form, exc):
    # Domain validations may concern several models; show their messages without
    # trying to attach a foreign model's field name to the current form.
    form.add_error(None, " ".join(exc.messages))


@require_GET
@inventory_access
def overview(request):
    query = request.GET.get("q", "").strip()[:150]
    status = request.GET.get("status", "active")
    if status not in {"active", "inactive", "low", "all"}:
        status = "active"
    products = products_with_stock(request.user, request.organization)
    if status == "inactive":
        products = products.filter(is_active=False)
    elif status != "all":
        products = products.filter(is_active=True)
        if status == "low":
            products = products.filter(stock_total__lte=F("minimum_stock"))
    if query:
        products = products.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(location__icontains=query))
    return render(request, "inventory/overview.html", _context(
        summary=stock_summary(request.user, request.organization), query=query, selected_status=status,
        **_page(request, products)))


@require_http_methods(["GET", "POST"])
@inventory_access
def product_edit(request, pk=None):
    product = get_object_or_404(_records(request, Product), pk=pk) if pk else None
    form = ProductForm(request.POST if request.method == "POST" else None,
        organization=request.organization, actor=request.user, instance=product)
    if request.method == "POST" and form.is_valid():
        try:
            saved = save_record(instance=form.save(commit=False), actor=request.user)
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, "Material salvo. Registre uma entrada para atualizar o saldo.")
            return redirect("inventory:product_detail", pk=saved.pk)
    return render(request, "inventory/form.html", _context(title="Editar material" if product else "Novo material", form=form,
        back_url=reverse("inventory:product_detail", args=[pk]) if product else reverse("inventory:overview"),
        submit_label="Salvar material", guide_title="MATERIAIS DE CONSUMO", guide_heading="O saldo nasce das movimentações",
        guide_text="Cadastre papel, materiais de limpeza, suprimentos e outros itens de consumo. Depois registre as entradas, as saídas ou a contagem de cada lote.",
        guide_extra="Computadores, móveis e outros bens individuais ficam na aba Patrimônio."))


@require_GET
@inventory_access
def product_detail(request, pk):
    product = get_object_or_404(products_with_stock(request.user, request.organization), pk=pk)
    lots = _records(request, StockLot).filter(product=product).order_by("expires_on", "code")
    movements = _records(request, Movement).filter(product=product).select_related("lot", "actor", "reversal")[:12]
    return render(request, "inventory/product_detail.html", _context(title=product.name, product=product, lots=lots,
        movements=movements, today=timezone.localdate(), soon=timezone.localdate() + timedelta(days=30)))


@require_GET
@inventory_access
def lot_list(request):
    today = timezone.localdate()
    query = request.GET.get("q", "").strip()[:150]
    status = request.GET.get("status", "available")
    if status not in {"available", "soon", "expired", "empty", "all"}:
        status = "available"
    lots = _records(request, StockLot).select_related("product")
    if query:
        lots = lots.filter(Q(code__icontains=query) | Q(product__name__icontains=query) | Q(product__code__icontains=query))
    if status == "empty":
        lots = lots.filter(quantity=0)
    elif status != "all":
        lots = lots.filter(quantity__gt=0)
        if status == "soon":
            lots = lots.filter(expires_on__gte=today, expires_on__lte=today + timedelta(days=30))
        elif status == "expired":
            lots = lots.filter(expires_on__lt=today)
    return render(request, "inventory/lots.html", _context(title="Lotes e validades", query=query, selected_status=status,
        today=today, soon=today + timedelta(days=30), **_page(request, lots)))


@require_http_methods(["GET", "POST"])
@inventory_access
def movement_create(request, product_pk=None):
    if product_pk is None:
        if request.method == "POST":
            # The selection page has no writes; its form is deliberately GET.
            from django.http import HttpResponseNotAllowed
            return HttpResponseNotAllowed(["GET"])
        selected = request.GET.get("product", "")
        if selected.isdigit():
            product = get_object_or_404(_records(request, Product), pk=selected, is_active=True)
            return redirect("inventory:product_movement", product_pk=product.pk)
        return render(request, "inventory/select_product.html", _context(tab="movements", title="Movimentar estoque",
            products=_records(request, Product).filter(is_active=True)))
    product = get_object_or_404(products_with_stock(request.user, request.organization), pk=product_pk, is_active=True)
    form = MovementForm(request.POST if request.method == "POST" else None,
        organization=request.organization, actor=request.user, product=product)
    form.fields["product"].disabled = True
    if request.method == "POST" and form.is_valid():
        try:
            movement = record_movement(organization=request.organization, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, "Movimentação registrada. O saldo do lote foi atualizado.")
            return redirect("inventory:product_detail", pk=movement.product_id)
    return render(request, "inventory/form.html", _context(tab="movements", title="Movimentar " + product.name, form=form,
        back_url=reverse("inventory:product_detail", args=[product.pk]), submit_label="Registrar movimentação",
        guide_title="CONFERÊNCIA POR LOTE", guide_heading="Cada alteração tem um motivo",
        guide_text="Entrada aumenta o saldo. Consumo e perda reduzem o lote selecionado. Na contagem física, informe a quantidade que realmente encontrou; o sistema registra a diferença.",
        guide_extra="Se houver erro, use Estornar no histórico. O lançamento original permanece registrado. A validade acompanha o lote até seu saldo acabar."))


@require_GET
@inventory_access
def movement_list(request):
    query = request.GET.get("q", "").strip()[:150]
    kind = request.GET.get("kind", "")
    records = _records(request, Movement).select_related("product", "lot", "actor", "reversal")
    if query:
        records = records.filter(Q(product__name__icontains=query) | Q(product__code__icontains=query) | Q(lot__code__icontains=query) | Q(reason__icontains=query))
    if kind in dict(Movement.Kind.choices):
        records = records.filter(kind=kind)
    else:
        kind = ""
    product_id = request.GET.get("product", "")
    if product_id.isdigit():
        get_object_or_404(_records(request, Product), pk=product_id)
        records = records.filter(product_id=product_id)
    return render(request, "inventory/movements.html", _context(tab="movements", title="Movimentações", query=query,
        selected_kind=kind, kind_choices=Movement.Kind.choices, **_page(request, records)))


@require_http_methods(["GET", "POST"])
@inventory_access
def movement_reverse(request, pk):
    movement = get_object_or_404(_records(request, Movement).select_related("product", "lot"), pk=pk)
    form = ReversalForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            reverse_movement(movement=movement, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, "Estorno registrado. A movimentação original permanece no histórico.")
            return redirect("inventory:product_detail", pk=movement.product_id)
    return render(request, "inventory/form.html", _context(tab="movements", title="Estornar movimentação", form=form,
        back_url=reverse("inventory:product_detail", args=[movement.product_id]), submit_label="Confirmar estorno",
        page_description=f"{movement.get_kind_display()} de {movement.quantity} {movement.product.unit} · {movement.product.name} · lote {movement.lot.code}",
        guide_heading="O estorno compensa o lançamento", guide_text="Uma nova movimentação será registrada com a quantidade inversa. O estorno só será concluído se não deixar o lote com saldo negativo.",
        guide_extra="Cada movimentação pode ser estornada uma vez. A justificativa fica visível no histórico."))


@require_GET
@inventory_access
def purchase_list(request):
    query = request.GET.get("q", "").strip()[:150]
    status = request.GET.get("status", "")
    records = _records(request, Purchase).select_related("supplier", "created_by").prefetch_related("items")
    if query:
        records = records.filter(Q(reference__icontains=query) | Q(supplier__name__icontains=query))
    if status in dict(Purchase.Status.choices):
        records = records.filter(status=status)
    else:
        status = ""
    return render(request, "inventory/purchases.html", _context(tab="purchases", title="Compras de materiais", query=query,
        selected_status=status, status_choices=Purchase.Status.choices, **_page(request, records)))


@require_http_methods(["GET", "POST"])
@inventory_access
def purchase_create(request):
    data = request.POST if request.method == "POST" else None
    form = PurchaseForm(data, organization=request.organization, actor=request.user)
    items = PurchaseItemFormSet(data, prefix="items", form_kwargs={"organization": request.organization, "actor": request.user})
    if request.method == "POST":
        valid_form, valid_items = form.is_valid(), items.is_valid()
        if valid_form and valid_items:
            rows = [{key: value for key, value in item.cleaned_data.items() if key != "DELETE"}
                for item in items if item.cleaned_data and not item.cleaned_data.get("DELETE")]
            try:
                purchase = create_purchase(organization=request.organization, actor=request.user, items=rows, **form.cleaned_data)
            except ValidationError as exc:
                _error(form, exc)
            else:
                messages.success(request, "Compra registrada. Confira os itens e confirme o recebimento para dar entrada no estoque.")
                return redirect("inventory:purchase_detail", pk=purchase.pk)
    return render(request, "inventory/purchase_form.html", _context(tab="purchases", title="Nova compra", form=form, item_forms=items,
        has_products=_records(request, Product).filter(is_active=True).exists()))


class ReceiptForm(forms.Form):
    confirmed = forms.BooleanField(label="Conferi os materiais, as quantidades, os lotes e as validades.")


def _purchase_context(request, purchase, receipt_form=None):
    return _context(tab="purchases", title=str(purchase), purchase=purchase,
        items=purchase.items.select_related("product", "movement", "movement__reversal"), receipt_form=receipt_form or ReceiptForm())


@require_GET
@inventory_access
def purchase_detail(request, pk):
    purchase = get_object_or_404(_records(request, Purchase).select_related("supplier", "created_by", "received_by"), pk=pk)
    return render(request, "inventory/purchase_detail.html", _purchase_context(request, purchase))


@require_POST
@inventory_access
def purchase_receive(request, pk):
    purchase = get_object_or_404(_records(request, Purchase).select_related("supplier", "created_by", "received_by"), pk=pk)
    form = ReceiptForm(request.POST)
    if form.is_valid():
        try:
            receive_purchase(purchase=purchase, actor=request.user)
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, "Recebimento confirmado. As entradas estão no histórico de estoque.")
            return redirect("inventory:purchase_detail", pk=purchase.pk)
    return render(request, "inventory/purchase_detail.html", _purchase_context(request, purchase, form))


@require_http_methods(["GET", "POST"])
@inventory_access
def purchase_cancel(request, pk):
    purchase = get_object_or_404(_records(request, Purchase), pk=pk)
    form = ReasonForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            cancel_purchase(purchase=purchase, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, "Compra cancelada. O registro e o motivo permanecem no histórico.")
            return redirect("inventory:purchase_detail", pk=purchase.pk)
    return render(request, "inventory/form.html", _context(tab="purchases", title="Cancelar compra", form=form,
        back_url=reverse("inventory:purchase_detail", args=[purchase.pk]), submit_label="Confirmar cancelamento",
        guide_heading="Somente compras não recebidas", guide_text="Cancele uma compra que ainda aguarda recebimento. Para corrigir itens, cancele e cadastre a compra novamente.",
        guide_extra="Se a compra já foi recebida, corrija o estoque pelos estornos das movimentações correspondentes."))


@require_GET
@inventory_access
def asset_list(request):
    query = request.GET.get("q", "").strip()[:150]
    status = request.GET.get("status", "")
    assets = _records(request, Asset).select_related("category", "custodian")
    if query:
        assets = assets.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(serial_number__icontains=query) | Q(location__icontains=query))
    if status in dict(Asset.Status.choices):
        assets = assets.filter(status=status)
    else:
        status = ""
    return render(request, "inventory/assets.html", _context(tab="assets", title="Patrimônio do escritório", query=query,
        selected_status=status, status_choices=Asset.Status.choices, **_page(request, assets)))


@require_http_methods(["GET", "POST"])
@inventory_access
def asset_edit(request, pk=None):
    asset = get_object_or_404(_records(request, Asset), pk=pk) if pk else None
    form = AssetForm(request.POST if request.method == "POST" else None, organization=request.organization, actor=request.user, instance=asset)
    if request.method == "POST" and form.is_valid():
        try:
            saved = save_record(instance=form.save(commit=False), actor=request.user, reason=form.cleaned_data["reason"])
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, "Patrimônio salvo com histórico da alteração.")
            return redirect("inventory:asset_detail", pk=saved.pk)
    return render(request, "inventory/form.html", _context(tab="assets", title="Atualizar patrimônio" if asset else "Novo patrimônio", form=form,
        back_url=reverse("inventory:asset_detail", args=[pk]) if asset else reverse("inventory:assets"), submit_label="Salvar patrimônio",
        guide_title="UM CADASTRO PARA CADA BEM", guide_heading="Acompanhe o equipamento ao longo do uso",
        guide_text="Registre computadores, móveis, impressoras e outros equipamentos com etiqueta própria. Cada mudança de localização, responsável ou situação preserva o motivo e o autor.",
        guide_extra="A baixa mantém o histórico. O valor de aquisição é informativo e não lança pagamentos no financeiro."))


def _asset_events(request, asset):
    labels = {"code": "Etiqueta", "name": "Bem", "serial_number": "Número de série", "category_id": "Categoria",
        "location": "Localização", "custodian_id": "Responsável", "acquired_on": "Aquisição",
        "acquisition_value": "Valor de aquisição", "status": "Situação", "notes": "Observações"}
    events = _records(request, AssetEvent).filter(asset=asset).select_related("actor")
    page_context = _page(request, events, 15)
    rows = []
    from django.contrib.auth import get_user_model
    category_names = dict(_records(request, Category).values_list("pk", "name"))
    # Historical custodians may no longer have an active membership; only IDs
    # recorded on this authorized asset's page are resolved below.
    custodian_ids = {entry.get("custodian_id") for event in page_context["page"] for entry in (event.before, event.after) if entry.get("custodian_id")}
    custodian_names = {user.pk: user.get_full_name() or user.email for user in get_user_model().objects.filter(pk__in=custodian_ids)}
    def display(key, value):
        if value is None or value == "":
            return "Não informado"
        if key == "status":
            return dict(Asset.Status.choices).get(value, value)
        if key == "category_id":
            return category_names.get(value, "Categoria anterior")
        if key == "custodian_id":
            return custodian_names.get(value, "Responsável anterior")
        if key == "acquisition_value":
            return "R$ " + str(value).replace(".", ",")
        if key == "acquired_on":
            try:
                from datetime import date
                return date.fromisoformat(value).strftime("%d/%m/%Y")
            except (ValueError, TypeError):
                return value
        return value
    for event in page_context["page"]:
        rows.append({"event": event, "created": not event.before, "changes": [
            {"label": label, "before": display(key, event.before.get(key)), "after": display(key, event.after.get(key))}
            for key, label in labels.items() if event.before.get(key) != event.after.get(key)]})
    return {**page_context, "event_rows": rows}


@require_GET
@inventory_access
def asset_detail(request, pk):
    asset = get_object_or_404(_records(request, Asset).select_related("category", "custodian"), pk=pk)
    return render(request, "inventory/asset_detail.html", _context(tab="assets", title=asset.name, asset=asset, **_asset_events(request, asset)))


@require_GET
@inventory_access
def catalog(request):
    # Independent pagination avoids unbounded supplier/customer selector pages.
    categories = Paginator(_records(request, Category), 20).get_page(request.GET.get("categories"))
    suppliers = Paginator(_records(request, Supplier), 20).get_page(request.GET.get("suppliers"))
    return render(request, "inventory/catalog.html", _context(tab="catalog", title="Categorias e fornecedores",
        categories=categories, suppliers=suppliers))


@require_http_methods(["GET", "POST"])
@inventory_access
def category_edit(request, pk=None):
    instance = get_object_or_404(_records(request, Category), pk=pk) if pk else None
    return _catalog_edit(request, CategoryForm, instance, "Editar categoria" if pk else "Nova categoria", "Salvar categoria")


@require_http_methods(["GET", "POST"])
@inventory_access
def supplier_edit(request, pk=None):
    instance = get_object_or_404(_records(request, Supplier), pk=pk) if pk else None
    return _catalog_edit(request, SupplierForm, instance, "Editar fornecedor" if pk else "Novo fornecedor", "Salvar fornecedor")


def _catalog_edit(request, form_class, instance, title, submit_label):
    form = form_class(request.POST if request.method == "POST" else None, organization=request.organization, actor=request.user, instance=instance)
    if request.method == "POST" and form.is_valid():
        try:
            save_record(instance=form.save(commit=False), actor=request.user)
        except ValidationError as exc:
            _error(form, exc)
        else:
            messages.success(request, "Cadastro salvo.")
            return redirect("inventory:catalog")
    return render(request, "inventory/form.html", _context(tab="catalog", title=title, form=form,
        back_url=reverse("inventory:catalog"), submit_label=submit_label))
