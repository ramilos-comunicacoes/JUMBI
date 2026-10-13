from django.contrib import admin
from django.urls import include, path
from apps.core.workspace_views import error403, error404, error500

urlpatterns = [
    path('seguranca/conta/', include('apps.security.urls')),
    path('rotinas/', include('apps.routines.urls')),
    path('honorarios/', include('apps.fees.urls')),
    path('portal/', include('apps.portal.urls')),
    path('admin/', admin.site.urls),
    path('juridico/', include('apps.legal.urls')),
    path('metas/', include('apps.performance.urls')),
    path('contratos/', include('apps.contracts.urls')),
    path('plataforma/', include('apps.core.platform_urls')),
    path('', include('apps.billing.urls')),
    path('', include('apps.core.workspace_urls')),
]

handler403 = error403
handler404 = error404
handler500 = error500
