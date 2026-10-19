from django.urls import path

from . import (
    views, calendar_views, kanban_views, profile_views, client_map_views,
    guide_views, my_routine_views, contact_views, djen_views, receipt_views,
    niche_views, djumbi_views,
)

app_name = "legal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("contadoria-prazos/", djumbi_views.contadoria_prazos_hub, name="contadoria_prazos"),
    path("pecas-minutas/", djumbi_views.pecas_minutas_hub, name="pecas_minutas"),
    path("correicao-ia/", djumbi_views.correicao_ia_hub, name="correicao_ia"),
    path("previdenciario/", niche_views.previdenciario_hub, name="previdenciario_hub"),
    path("demandas/<int:pk>/<slug:action>/", niche_views.demand_action, name="demand_action"),
    path("trabalhista/", niche_views.trabalhista_hub, name="trabalhista_hub"),
    path("minha-rotina/", my_routine_views.my_routine, name="my_routine"),
    path("minha-rotina/redistribuir/", my_routine_views.bulk_reassign_tasks, name="bulk_reassign_tasks"),
    path("contatos/mensagens/", contact_views.contact_messages_list, name="contact_messages_list"),
    path("contatos/mensagens/<int:pk>/", contact_views.contact_message_detail, name="contact_message_detail"),
    path("contatos/mensagens/<int:pk>/abrir/", contact_views.contact_message_open_link, name="contact_message_open_link"),
    path("contatos/mensagens/<int:pk>/concluir/", contact_views.contact_message_complete, name="contact_message_complete"),
    path("djen/", djen_views.djen_dashboard, name="djen_dashboard"),
    path("djen/executar/", djen_views.djen_execute_search, name="djen_execute_search"),
    path("djen/<int:pk>/relatorio-word/", djen_views.djen_download_word_report, name="djen_download_word_report"),
    path("recibos/<int:pk>/baixar-docx/", receipt_views.download_receipt_docx, name="receipt_download_docx"),
    path("recibos/<int:pk>/imprimir/", receipt_views.receipt_printable, name="receipt_printable"),
    path("mapa-clientes/", client_map_views.client_map, name="client_map"),
    path("como-usar/", guide_views.guide, name="guide"),
    path("calendario/", calendar_views.calendar_view, name="calendar"),
    path("quadro/", kanban_views.board, name="kanban"),
    path("quadro/<int:pk>/mover/", kanban_views.move, name="kanban_move"),
    path("exportar/", views.export_workspace, name="export"),
    path("pasta/<int:pk>/exportar/", views.export_workspace, name="export_matter"),
    path("pessoa/<int:pk>/", profile_views.contact_detail, name="contact_detail"),
    path("pessoa/<int:pk>/excluir/", profile_views.contact_delete, name="contact_delete"),
    path("contatos/<int:pk>/excluir/", profile_views.contact_delete, name="contact_delete_alt"),
    path("documento/<int:pk>/", profile_views.document_detail, name="document_detail"),
    path("arquivo/<int:pk>/", views.document_download, name="document_download"),
    path("documento/<int:pk>/versao/", views.document_upload, name="document_upload"),
    path("pasta/<int:pk>/", views.matter_detail, name="detail"),
    path("<slug:module>/", views.record_list, name="list"),
    path("<slug:module>/novo/", views.record_form, name="create"),
    path("<slug:module>/<int:pk>/editar/", views.record_form, name="edit"),
    path("<slug:module>/<int:pk>/<slug:action>/", views.record_action, name="action"),
]

