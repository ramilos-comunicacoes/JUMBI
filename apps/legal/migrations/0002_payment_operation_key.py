import uuid

from django.db import migrations, models


def populate_operation_keys(apps, schema_editor):
    Payment = apps.get_model("legal", "Payment")
    database = schema_editor.connection.alias
    for payment_id in Payment.objects.using(database).filter(operation_key__isnull=True).values_list("pk", flat=True).iterator():
        Payment.objects.using(database).filter(pk=payment_id).update(operation_key=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [("legal", "0001_initial")]

    operations = [
        migrations.AddField(model_name="payment", name="operation_key", field=models.UUIDField(null=True, editable=False)),
        migrations.RunPython(populate_operation_keys, migrations.RunPython.noop),
        migrations.AlterField(model_name="payment", name="operation_key", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
    ]
