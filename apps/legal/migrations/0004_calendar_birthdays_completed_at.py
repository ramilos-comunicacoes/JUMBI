from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legal", "0003_legacy_import_provenance")]

    operations = [
        migrations.AddField(
            model_name="contact", name="birth_date",
            field=models.DateField("Data de nascimento", null=True, blank=True),
        ),
        migrations.AddField(
            model_name="appointment", name="kind",
            field=models.CharField("Tipo", max_length=20, default="other", db_default="other", choices=[
                ("meeting", "Reunião"), ("hearing", "Audiência"),
                ("important_date", "Data importante"), ("other", "Outro compromisso"),
            ]),
        ),
        migrations.AddField(
            model_name="task", name="completed_at",
            field=models.DateTimeField(null=True, blank=True, editable=False),
        ),
    ]
