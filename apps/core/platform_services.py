from uuid import uuid4

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.text import slugify

from apps.billing.models import OrganizationSubscription, SubscriptionEvent
from .models import AuditLog, Membership, Organization, User


def require_platform_admin(user):
    if not user.is_authenticated or not user.is_active or not user.is_superuser:
        raise PermissionDenied("Esta área é exclusiva da administração da plataforma.")


@transaction.atomic
def create_office(*, actor, data):
    require_platform_admin(actor)
    email = data["owner_email"].strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError("Já existe uma conta com este e-mail.")
    user = User(email=email, first_name=data["owner_name"].strip(), is_staff=False, is_superuser=False)
    validate_password(data["password"], user)
    user.set_password(data["password"])
    user.full_clean()
    user.save()
    organization = Organization(
        name=data["name"], slug=f"{slugify(data['name'])[:35] or 'escritorio'}-{uuid4().hex[:12]}",
        business_type="office", contact_email=data.get("contact_email", ""),
        contact_phone=data.get("contact_phone", ""), practice_areas=data["practice_areas"],
    )
    organization.full_clean()
    organization.save()
    Membership.objects.create(organization=organization, user=user, role="owner")
    subscription = OrganizationSubscription(
        organization=organization, plan=data["plan"], status=data["subscription_status"],
    )
    subscription.full_clean()
    subscription.save()
    SubscriptionEvent.objects.create(subscription=subscription, actor=actor, description="Escritório criado pela administração da plataforma. Situação de acesso definida manualmente; não representa baixa de pagamento.")
    AuditLog.objects.create(organization=organization, actor=actor, action="platform.office_created", metadata={
        "owner_id": user.pk, "practice_areas": organization.practice_areas,
        "plan": subscription.plan, "subscription_status": subscription.status,
    })
    return organization


@transaction.atomic
def configure_office(*, actor, office_id, data):
    require_platform_admin(actor)
    organization = Organization.objects.select_for_update().get(pk=office_id, business_type="office")
    previous = list(organization.practice_areas)
    for field in ("name", "contact_email", "contact_phone", "practice_areas"):
        setattr(organization, field, data[field])
    organization.full_clean()
    organization.save(update_fields=["name", "contact_email", "contact_phone", "practice_areas", "updated_at"])
    AuditLog.objects.create(organization=organization, actor=actor, action="platform.office_configured", metadata={
        "previous_practice_areas": previous, "practice_areas": organization.practice_areas,
    })
    return organization
