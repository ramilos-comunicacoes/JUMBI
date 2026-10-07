from django.urls import path
from django.views.generic import RedirectView
from . import workspace_views as views
from .platform_views import platform_dashboard

app_name = "core"
urlpatterns = [
    path("plataforma/", platform_dashboard, name="platform"),
    path("", views.home, name="home"),
    path("saude/", views.health, name="health"),
    path("entrar/", views.WorkspaceLoginView.as_view(), name="login"),
    path("cadastro/", views.signup, name="signup"),
    path("sair/", views.WorkspaceLogoutView.as_view(), name="logout"),
    path("seguranca/senha/", views.WorkspacePasswordChangeView.as_view(), name="password_change"),
    path("painel/", RedirectView.as_view(pattern_name="legal:dashboard"), name="dashboard"),
    path("equipe/", views.team, name="team"),
    path("equipe/<int:pk>/revogar/", views.revoke_membership, name="revoke_member"),
    path("convites/<int:pk>/revogar/", views.revoke_invitation, name="revoke_invitation"),
    path("convite/<str:token>/", views.accept_invitation, name="invitation"),
    path("organizacao/selecionar/", views.switch_organization, name="switch_organization"),
    path("auditoria/", views.audit_trail, name="audit"),
]
