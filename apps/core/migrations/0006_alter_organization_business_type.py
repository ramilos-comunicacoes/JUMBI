from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_organizationrole_membership_hierarchy"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organization",
            name="business_type",
            field=models.CharField(
                choices=[
                    ("office", "Jurídico"),
                    ("engineering", "Engenharia"),
                    ("agro", "Agro"),
                    ("retail", "Varejo"),
                    ("other", "Outro"),
                ],
                default="other",
                max_length=20,
                verbose_name="segmento",
            ),
        ),
    ]
