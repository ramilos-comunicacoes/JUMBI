import decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("core", "0002_organization_business_data")]
    operations = [
        migrations.CreateModel(name="Farm", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("name", models.CharField(max_length=180)), ("city", models.CharField(blank=True, max_length=100)), ("state", models.CharField(blank=True, max_length=2)), ("total_area_hectares", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=12)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="farms", to="core.organization")),
        ], options={"ordering": ["name"]}),
        migrations.CreateModel(name="Field", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("name", models.CharField(max_length=160)), ("crop", models.CharField(blank=True, max_length=100)), ("area_hectares", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=12)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("farm", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fields", to="agro.farm")),
        ], options={"ordering": ["farm__name", "name"]}),
    ]
