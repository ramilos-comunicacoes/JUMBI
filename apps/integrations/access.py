from django.core.exceptions import PermissionDenied
from django.db.models import Q
from apps.core.models import Membership
from apps.legal.services import visible_matters
from .models import CourtCommunication


def require_integration_manager(user, organization):
    if not organization or not Membership.objects.filter(user=user, user__is_active=True, organization=organization,
            organization__status="active", organization__business_type="office", is_active=True, role__in=["owner", "manager"]).exists():
        raise PermissionDenied("Integrações são administradas pela direção e gestão do escritório.")


def visible_communications(user, organization):
    from apps.legal.models import CourtCase
    matters = visible_matters(user, organization)
    hidden_numbers = CourtCase.objects.filter(organization=organization).exclude(matter__in=matters).values("number")
    return CourtCommunication.objects.filter(organization=organization).filter(
        Q(matter__in=matters) | Q(matter__isnull=True)
    ).exclude(case_number__in=hidden_numbers)
