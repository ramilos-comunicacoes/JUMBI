from django.urls import path

from .views import opportunity_convert, opportunity_status, partner_status, portal

app_name = "partners"

urlpatterns = [
    path("", portal, name="portal"),
    path("gestao/parceiros/<int:pk>/status/", partner_status, name="partner-status"),
    path("gestao/oportunidades/<int:pk>/status/", opportunity_status, name="opportunity-status"),
    path("gestao/oportunidades/<int:pk>/converter/", opportunity_convert, name="opportunity-convert"),
]
