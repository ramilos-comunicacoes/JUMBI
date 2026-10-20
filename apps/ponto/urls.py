from django.urls import path
from . import views

app_name = "ponto"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("bater/", views.clock_in_kiosk, name="clock_in"),
    path("bater/kiosk/", views.clock_in_kiosk, name="clock_in_kiosk"),
    path("api/punch/", views.register_punch_api, name="punch_api"),
    path("api/registrar/", views.register_punch_api, name="register_punch_api"),
    path("meu-espelho/", views.my_timesheet, name="my_timesheet"),
    path("equipe/", views.team_timesheet, name="team_timesheet"),
    path("equipe/padrao/", views.team_timesheet, name="team_timesheet_default"),
    path("batidas/manual/", views.manual_punch_create, name="manual_punch_create"),
    path("batidas/<int:pk>/excluir/", views.manual_punch_delete, name="manual_punch_delete"),
    path("solicitacoes/", views.adjustment_requests_list, name="adjustments_list"),
    path("solicitacoes/todas/", views.adjustment_requests_list, name="adjustment_requests_list"),
    path("solicitacoes/nova/", views.adjustment_request_create, name="adjustment_create"),
    path("solicitacoes/criar/", views.adjustment_request_create, name="adjustment_request_create"),
    path("solicitacoes/<int:pk>/decidir/", views.adjustment_request_decide, name="adjustment_decide"),
    path("solicitacoes/<int:pk>/julgar/", views.adjustment_request_decide, name="adjustment_request_decide"),
    path("jornadas/", views.schedules_manage, name="schedules_manage"),
    path("jornadas/nova/", views.schedule_edit, name="schedule_create"),
    path("jornadas/<int:pk>/editar/", views.schedule_edit, name="schedule_edit"),
    path("feriados/", views.holidays_manage, name="holidays_manage"),
    path("feriados/<int:pk>/excluir/", views.holiday_delete, name="holiday_delete"),
    path("espelho/imprimir/", views.export_timesheet_print, name="export_print"),
    path("espelho/<int:membership_id>/imprimir/", views.export_timesheet_print, name="export_timesheet_print"),
    path("espelho/csv/", views.export_timesheet_csv, name="export_csv"),
    path("espelho/<int:membership_id>/csv/", views.export_timesheet_csv, name="export_timesheet_csv"),
]
