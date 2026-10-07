from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("engineering", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
