from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from apps.core.models import Organization, Membership
from .models import OrganizationSubscription
from .plans import PLANS


def subscription_for(organization):
    if organization is None:
        return None
    return OrganizationSubscription.objects.filter(organization=organization).first()


def has_advanced(organization):
    if not settings.JUMBI_ENFORCE_SUBSCRIPTIONS:
        return True
    subscription = subscription_for(organization)
    return bool(subscription and subscription.is_available and subscription.limits["advanced"])


def require_access(organization, *, advanced=False):
    if not settings.JUMBI_ENFORCE_SUBSCRIPTIONS:
        return None
    subscription = subscription_for(organization)
    if not subscription or not subscription.is_available:
        raise PermissionDenied("A assinatura deste escritório precisa ser ativada pela administração.")
    if advanced and not subscription.limits["advanced"]:
        raise PermissionDenied("Este recurso está disponível no plano Max.")
    return subscription


def usage(organization):
    from apps.legal.models import Matter, DocumentVersion
    return {
        "members": Membership.objects.filter(organization=organization, is_active=True, user__is_active=True).count(),
        "matters": Matter.objects.filter(organization=organization).exclude(status="closed").count(),
        "versions": DocumentVersion.objects.filter(organization=organization).count(),
    }


def check_capacity(organization, resource, *, instance=None, user=None):
    """Called inside the write transaction; serialize quota consumers per office."""
    if not settings.JUMBI_ENFORCE_SUBSCRIPTIONS:
        return
    Organization.objects.select_for_update().get(pk=organization.pk)
    subscription = require_access(organization)
    limit = subscription.limits[resource]
    if limit is None:
        return
    from apps.legal.models import Matter, DocumentVersion
    if resource == "members":
        if user and Membership.objects.filter(organization=organization, user=user, is_active=True, user__is_active=True).exists():
            return
        count = Membership.objects.filter(organization=organization, is_active=True, user__is_active=True).count()
    elif resource == "matters":
        if instance.status == "closed":
            return
        if instance.pk and Matter.objects.filter(pk=instance.pk, organization=organization).exclude(status="closed").exists():
            return
        count = Matter.objects.filter(organization=organization).exclude(status="closed").count()
    else:
        count = DocumentVersion.objects.filter(organization=organization).count()
    if count >= limit:
        labels = {"members": "usuários ativos", "matters": "pastas ativas", "versions": "versões de documentos"}
        raise ValidationError(f"Limite do plano {subscription.limits['name']}: {subscription.limits[resource]} {labels[resource]}. Consulte sua assinatura.")


def validate_plan_change(organization, plan, *, is_partner=False):
    if plan not in PLANS:
        raise ValidationError("Escolha um plano válido.")
    if is_partner:
        return
    current = usage(organization)
    for resource, count in current.items():
        if count > PLANS[plan][resource]:
            raise ValidationError("O uso atual excede os limites do plano escolhido. Preserve os registros e ajuste a capacidade antes de mudar o plano.")
