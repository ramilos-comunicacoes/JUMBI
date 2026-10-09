import apps.core.niches
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0007_workspaceinvitation")]
    operations = [migrations.AddField(
        model_name="organization", name="practice_areas",
        field=models.JSONField(blank=True, default=list, db_default=[], validators=[apps.core.niches.validate_practice_areas], verbose_name="áreas de atuação"),
    )]
