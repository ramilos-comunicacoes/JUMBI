from django.urls import path
from . import views

app_name = "portal"
urlpatterns = [
    path("", views.home, name="home"),
    path("gestao/", views.manage, name="manage"),
    path("vinculos/novo/", views.access_create, name="access_create"),
    path("vinculos/<int:pk>/revogar/", views.revoke_record, {"kind": "access"}, name="access_revoke"),
    path("revisoes/nova/", views.review_create, name="review_create"),
    path("revisoes/<int:pk>/", views.review_detail, name="review"),
    path("revisoes/<int:pk>/publicar/", views.publish, name="publish"),
    path("documentos/<int:pk>/", views.publication_detail, name="publication"),
    path("documentos/<int:pk>/baixar/", views.download, name="download"),
    path("documentos/<int:pk>/revogar/", views.revoke_record, {"kind": "publication"}, name="publication_revoke"),
]
