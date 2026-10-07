from django.urls import path

from .views import UserLoginView, UserLogoutView, UserPasswordChangeView, access, control_panel, dashboard, segment_login, signup, switch_organization

app_name = "core"
urlpatterns = [
    path("entrar/", UserLoginView.as_view(), name="login"),
    path("acessar/", access, name="access"),
    path("acessar/<slug:segment>/", segment_login, name="segment-login"),
    path("sair/", UserLogoutView.as_view(), name="logout"),
    path("seguranca/senha/", UserPasswordChangeView.as_view(), name="password-change"),
    path("cadastro/", signup, name="signup"),
    path("painel/", dashboard, name="dashboard"),
    path("organizacao/selecionar/", switch_organization, name="switch-organization"),
    path("controle/", control_panel, name="control-panel"),
    path("controle/<slug:section>/", control_panel, name="control-section"),
]
