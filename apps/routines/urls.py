from django.urls import path
from . import views

app_name = "routines"
urlpatterns = [
    path("", views.template_list, name="list"),
    path("nova/", views.template_edit, name="create"),
    path("exemplo/<slug:key>/", views.template_import, name="import"),
    path("modelo/<int:pk>/", views.template_detail, name="detail"),
    path("modelo/<int:pk>/editar/", views.template_edit, name="edit"),
    path("pasta/<int:pk>/", views.matter_routine, name="matter"),
    path("conferencia/<int:pk>/", views.check_status, name="check"),
]
