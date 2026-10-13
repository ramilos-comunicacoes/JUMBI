from django.urls import path

from . import views

app_name = "fees"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("novo/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
]
