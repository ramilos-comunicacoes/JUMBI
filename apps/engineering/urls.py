from django.urls import path

from .views import project_status, task_status, workspace

app_name = "engineering"
urlpatterns = [
    path("", workspace, name="workspace"),
    path("obras/<int:pk>/status/", project_status, name="project-status"),
    path("tarefas/<int:pk>/status/", task_status, name="task-status"),
    path("modulo/<slug:section>/", workspace, name="section"),
]
