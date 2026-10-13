from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.billing.services import has_advanced
from .views import organization_required


@organization_required
@require_GET
def guide(request):
    return render(request, 'legal/guide.html', {
        'page_title': 'Como usar o JUMBI', 'active_nav': 'guide',
        'advanced_access': has_advanced(request.organization),
    })
