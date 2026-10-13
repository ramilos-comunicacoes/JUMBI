from django.urls import path
from . import views

app_name = "discovery"
urlpatterns = [
    path("", views.search, name="search"),
    path("salvar/", views.save, name="save"),
    path("salvas/<int:pk>/", views.open_saved, name="open_saved"),
    path("salvas/<int:pk>/excluir/", views.delete, name="delete"),
]
