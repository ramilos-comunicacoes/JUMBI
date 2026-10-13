from django.urls import path
from . import views

app_name = "inventory"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("lotes/", views.lot_list, name="lots"),
    path("materiais/novo/", views.product_edit, name="product_create"),
    path("materiais/<int:pk>/", views.product_detail, name="product_detail"),
    path("materiais/<int:pk>/editar/", views.product_edit, name="product_edit"),
    path("materiais/<int:product_pk>/movimentar/", views.movement_create, name="product_movement"),
    path("movimentacoes/", views.movement_list, name="movements"),
    path("movimentacoes/nova/", views.movement_create, name="movement_create"),
    path("movimentacoes/<int:pk>/estornar/", views.movement_reverse, name="movement_reverse"),
    path("compras/", views.purchase_list, name="purchases"),
    path("compras/nova/", views.purchase_create, name="purchase_create"),
    path("compras/<int:pk>/", views.purchase_detail, name="purchase_detail"),
    path("compras/<int:pk>/receber/", views.purchase_receive, name="purchase_receive"),
    path("compras/<int:pk>/cancelar/", views.purchase_cancel, name="purchase_cancel"),
    path("patrimonio/", views.asset_list, name="assets"),
    path("patrimonio/novo/", views.asset_edit, name="asset_create"),
    path("patrimonio/<int:pk>/", views.asset_detail, name="asset_detail"),
    path("patrimonio/<int:pk>/editar/", views.asset_edit, name="asset_edit"),
    path("cadastros/", views.catalog, name="catalog"),
    path("categorias/nova/", views.category_edit, name="category_create"),
    path("categorias/<int:pk>/editar/", views.category_edit, name="category_edit"),
    path("fornecedores/novo/", views.supplier_edit, name="supplier_create"),
    path("fornecedores/<int:pk>/editar/", views.supplier_edit, name="supplier_edit"),
]
