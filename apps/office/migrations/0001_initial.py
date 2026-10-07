from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("core", "0002_organization_business_data"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="Client", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=160)), ("email", models.EmailField(blank=True, max_length=254)), ("phone", models.CharField(blank=True, max_length=30)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="office_clients", to="core.organization")),
        ], options={"ordering": ["name"]}),
        migrations.CreateModel(name="WorkItem", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("title", models.CharField(max_length=180)),
            ("status", models.CharField(choices=[("todo", "A fazer"), ("in_progress", "Em andamento"), ("done", "Concluida")], default="todo", max_length=20)), ("due_date", models.DateField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("client", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="work_items", to="office.client")),
            ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="office_work_items", to="core.organization")),
            ("owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_work_items", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["status", "due_date", "title"]}),
    ]
