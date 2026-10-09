from django.urls import path
from . import views

app_name = "performance"
urlpatterns = [
    path("", views.goal_list, name="list"),
    path("nova/", views.goal_edit, name="create"),
    path("<int:pk>/editar/", views.goal_edit, name="edit"),
    path("<int:pk>/progresso/", views.goal_progress, name="progress"),
]
