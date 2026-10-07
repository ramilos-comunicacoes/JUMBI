from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_organization_brand_accent_color_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationRole",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, verbose_name="nome do cargo")),
                ("description", models.CharField(blank=True, max_length=240, verbose_name="responsabilidades")),
                (
                    "hierarchy_level",
                    models.PositiveSmallIntegerField(
                        help_text="Números menores representam cargos mais altos. Ex.: CEO e gerente 10, funcionário 70.",
                        verbose_name="nível hierárquico",
                    ),
                ),
                (
                    "permission_role",
                    models.CharField(
                        choices=[
                            ("owner", "Direção / controle total"),
                            ("manager", "Gestão"),
                            ("operator", "Operação"),
                            ("viewer", "Somente consulta"),
                        ],
                        default="operator",
                        max_length=20,
                        verbose_name="perfil de permissões",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="ativo")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="roles",
                        to="core.organization",
                    ),
                ),
            ],
            options={"ordering": ["hierarchy_level", "name"]},
        ),
        migrations.AddConstraint(
            model_name="organizationrole",
            constraint=models.UniqueConstraint(
                fields=("organization", "name"),
                name="unique_organization_role_name",
            ),
        ),
        migrations.AddField(
            model_name="membership",
            name="position",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="memberships",
                to="core.organizationrole",
                verbose_name="cargo",
            ),
        ),
        migrations.AddField(
            model_name="membership",
            name="reports_to",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="direct_reports",
                to="core.membership",
                verbose_name="gestor direto",
            ),
        ),
    ]
