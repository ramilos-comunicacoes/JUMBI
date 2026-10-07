from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DemoRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, verbose_name="nome")),
                ("work_email", models.EmailField(max_length=254, verbose_name="e-mail profissional")),
                ("company", models.CharField(max_length=150, verbose_name="empresa")),
                ("segment", models.CharField(choices=[("engenharia", "Engenharia"), ("juridico", "Jurídico"), ("agro", "Agro"), ("outro", "Outro")], max_length=20, verbose_name="segmento")),
                ("message", models.TextField(blank=True, verbose_name="mensagem")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "solicitação de demonstração", "verbose_name_plural": "solicitações de demonstração", "ordering": ["-created_at"]},
        ),
    ]
