from django.urls import path
from . import views

app_name = 'security'
urlpatterns = [
    path('', views.account, name='account'),
    path('confirmar/', views.challenge, name='challenge'),
]
