from django.urls import path
from . import views

app_name = "marketing"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("leads/", views.leads_kanban, name="leads_kanban"),
    path("leads/novo/", views.lead_create, name="lead_create"),
    path("leads/<int:lead_id>/editar/", views.lead_edit, name="lead_edit"),
    path("leads/<int:lead_id>/stage/", views.lead_update_stage, name="lead_update_stage"),
    path("leads/<int:lead_id>/converter/", views.lead_convert_view, name="lead_convert"),
    path("campanhas/", views.campaign_list, name="campaign_list"),
    path("campanhas/nova/", views.campaign_create, name="campaign_create"),
    path("campanhas/<int:campaign_id>/editar/", views.campaign_edit, name="campaign_edit"),
    path("utm/", views.utm_builder, name="utm_builder"),
    path("despesas/", views.expense_list, name="expense_list"),
]
