from django.urls import path

from .views import operation_status, workspace

app_name = "agro"
urlpatterns = [
    path("", workspace, name="workspace"),
    path("operacoes/<int:pk>/status/", operation_status, name="operation-status"),
    path("modulo/<slug:section>/", workspace, name="section"),
]
