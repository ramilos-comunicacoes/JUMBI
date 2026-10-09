from django.urls import path
from . import views

app_name = "contracts"
urlpatterns = [
    path("", views.library, name="library"),
    path("modelos/novo/", views.template_edit, name="template_create"),
    path("modelos/<int:pk>/editar/", views.template_edit, name="template_edit"),
    path("modelos/<int:pk>/arquivar/", views.template_archive, name="template_archive"),
    path("modelos/<int:template_pk>/preencher/", views.build, name="build"),
    path("documentos/", views.history, name="history"),
    path("documentos/<int:pk>/", views.detail, name="detail"),
    path("documentos/<int:contract_pk>/revisar/", views.build, name="revise"),
    path("versoes/<int:pk>/imprimir/", views.print_revision, name="print"),
    path("versoes/<int:pk>/baixar/", views.download, name="download"),
]
