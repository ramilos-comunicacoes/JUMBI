from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0003_membership_rbac_auditlog"),
        ("engineering", "0002_project_updated_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("todo", "A fazer"), ("doing", "Em progresso"), ("review", "Aguardando aprovacao"), ("done", "Concluida")], db_index=True, default="todo", max_length=20)),
                ("priority", models.CharField(choices=[("low", "Baixa"), ("normal", "Normal"), ("high", "Alta"), ("critical", "Critica")], default="normal", max_length=20)),
                ("due_date", models.DateField(blank=True, db_index=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assignee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="engineering_tasks", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_engineering_tasks", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="engineering_tasks", to="core.organization")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tasks", to="engineering.project")),
            ],
            options={"ordering": ["status", "due_date", "-priority", "title"]},
        ),
        migrations.CreateModel(
            name="ProjectEvidence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("notes", models.TextField(blank=True)),
                ("file", models.FileField(blank=True, upload_to="engineering/evidences/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="engineering_evidences", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="engineering_evidences", to="core.organization")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidences", to="engineering.project")),
                ("task", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="evidences", to="engineering.projecttask")),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
