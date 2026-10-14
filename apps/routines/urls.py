from django.urls import path
from . import views

app_name = "routines"
urlpatterns = [
    path("", views.template_list, name="list"),
    path("tutoriais/novo/", views.tutorial_create, name="tutorial_create"),
    path("tutoriais/<int:pk>/", views.tutorial_detail, name="tutorial_detail"),
    path("tutoriais/<int:pk>/editar/", views.tutorial_edit, name="tutorial_edit"),
    path("tutoriais/<int:pk>/excluir/", views.tutorial_delete, name="tutorial_delete"),
    path("nova/", views.template_edit, name="create"),
    path("exemplo/<slug:key>/", views.template_import, name="import"),
    path("modelo/<int:pk>/", views.template_detail, name="detail"),
    path("modelo/<int:pk>/editar/", views.template_edit, name="edit"),
    path("pasta/<int:pk>/", views.matter_routine, name="matter"),
    path("conferencia/<int:pk>/", views.check_status, name="check"),
]
