from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def normalize_membership_roles(apps, schema_editor):
    Membership = apps.get_model("core", "Membership")
    Membership.objects.filter(role="admin").update(role="manager")
    Membership.objects.filter(role="member").update(role="operator")


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0002_organization_business_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="membership",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(normalize_membership_roles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="membership",
            name="role",
            field=models.CharField(
                choices=[("owner", "Proprietario"), ("manager", "Gestor"), ("operator", "Operador"), ("viewer", "Consulta")],
                default="operator",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=140)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_logs", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="audit_logs", to="core.organization")),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["organization", "created_at"], name="core_auditl_organiz_c79039_idx"),
                    models.Index(fields=["action"], name="core_auditl_action_d9fb24_idx"),
                ],
            },
        ),
    ]
