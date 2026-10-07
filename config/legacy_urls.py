from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path, re_path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("juridico/", include("apps.office.urls")),
    path("parceiros/", include("apps.partners.urls")),
    re_path(r"^office(?:/.*)?$", RedirectView.as_view(pattern_name="office:workspace", permanent=True)),
    path("engenharia/", include("apps.engineering.urls")),
    path("agro/", include("apps.agro.urls")),
    path("", include("apps.pages.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
