from django.urls import path

from . import views

app_name = "legal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("exportar/", views.export_workspace, name="export"),
    path("arquivo/<int:pk>/", views.document_download, name="document_download"),
    path("documento/<int:pk>/versao/", views.document_upload, name="document_upload"),
    path("pasta/<int:pk>/", views.matter_detail, name="detail"),
    path("<slug:module>/", views.record_list, name="list"),
    path("<slug:module>/novo/", views.record_form, name="create"),
    path("<slug:module>/<int:pk>/editar/", views.record_form, name="edit"),
    path("<slug:module>/<int:pk>/<slug:action>/", views.record_action, name="action"),
]
