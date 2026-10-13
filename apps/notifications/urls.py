from django.urls import path

from . import views

app_name = "notifications"
urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("ler-todas/", views.read_all, name="read_all"),
    path("<int:pk>/<str:action>/", views.state, name="state"),
]
