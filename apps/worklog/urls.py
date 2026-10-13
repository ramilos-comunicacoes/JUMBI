from django.urls import path
from . import views

app_name = "worklog"
urlpatterns = [path("<int:pk>/", views.task_detail, name="task")]
