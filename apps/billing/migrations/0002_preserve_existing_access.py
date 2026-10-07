from django.db import migrations


def preserve_existing(apps, schema_editor):
    Organization = apps.get_model("core", "Organization")
    Subscription = apps.get_model("billing", "OrganizationSubscription")
    Event = apps.get_model("billing", "SubscriptionEvent")
    for organization in Organization.objects.filter(business_type="office"):
        subscription, created = Subscription.objects.get_or_create(organization=organization, defaults={
            "plan": "max", "status": "demo" if "demonstracao" in organization.slug else "active",
            "notes": "Acesso preexistente preservado na migração. Conferir condições comerciais antes da próxima renovação; nenhum pagamento inferido.",
        })
        if created:
            Event.objects.create(subscription=subscription, description="Migração preservou acesso preexistente; não representa contratação ou pagamento novo.")


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(preserve_existing, migrations.RunPython.noop)]
