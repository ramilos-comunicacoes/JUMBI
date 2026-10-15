from django.urls import path
from .platform_views import office_configure, office_create, office_access

app_name = "platform"
urlpatterns = [
    path("escritorios/novo/", office_create, name="office_create"),
    path("escritorios/<int:pk>/configurar/", office_configure, name="office_configure"),
    path("escritorios/<int:pk>/acesso/", office_access, name="office_access"),
]
