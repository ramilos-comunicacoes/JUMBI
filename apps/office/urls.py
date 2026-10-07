from django.urls import path

from .views import case_status, finance_paid, purchase_paid, task_status, workspace

app_name = "office"
urlpatterns = [
    path("", workspace, name="workspace"),
    path("tarefas/<int:pk>/status/", task_status, name="task-status"),
    path("processos/<int:pk>/status/", case_status, name="case-status"),
    path("financeiro/<int:pk>/situacao/", finance_paid, name="finance-paid"),
    path("compras/<int:pk>/situacao/", purchase_paid, name="purchase-paid"),
    path("modulo/<slug:section>/", workspace, name="section"),
]
