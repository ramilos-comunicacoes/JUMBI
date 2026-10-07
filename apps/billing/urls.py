from django.urls import path
from . import views
app_name = "billing"
urlpatterns = [
    path("assinatura/", views.subscription, name="subscription"),
    path("contratar/<slug:plan>/", views.contact, name="contact"),
]
