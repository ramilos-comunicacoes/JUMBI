import decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("core", "0002_organization_business_data")]
    operations = [
        migrations.CreateModel(name="Supplier", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("name", models.CharField(max_length=180)),
            ("document", models.CharField(blank=True, max_length=18)), ("email", models.EmailField(blank=True, max_length=254)), ("phone", models.CharField(blank=True, max_length=30)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="engineering_suppliers", to="core.organization")),
        ], options={"ordering": ["name"]}),
        migrations.CreateModel(name="Project", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("name", models.CharField(max_length=180)), ("client_name", models.CharField(blank=True, max_length=180)),
            ("status", models.CharField(choices=[("planning", "Planejamento"), ("active", "Em execucao"), ("completed", "Concluido")], default="planning", max_length=20)), ("budget", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=14)), ("start_date", models.DateField(blank=True, null=True)), ("end_date", models.DateField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="engineering_projects", to="core.organization")),
        ], options={"ordering": ["status", "name"]}),
    ]
