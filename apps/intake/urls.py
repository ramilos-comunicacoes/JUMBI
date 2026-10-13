from django.urls import path
from . import views

app_name = "intake"
urlpatterns = [
    path("", views.home, name="home"),
    path("modelo/<str:kind>.<str:extension>", views.template, name="template"),
    path("<uuid:pk>/", views.preview, name="preview"),
    path("<uuid:pk>/confirmar/", views.confirm, name="confirm"),
    path("<uuid:pk>/descartar/", views.discard, name="discard"),
]
