from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.AddField(model_name="organization", name="business_type", field=models.CharField(choices=[("office", "Office"), ("engineering", "Engenharia"), ("agro", "Agro"), ("retail", "Varejo"), ("other", "Outro")], default="other", max_length=20, verbose_name="segmento")),
        migrations.AddField(model_name="organization", name="city", field=models.CharField(blank=True, max_length=100, verbose_name="cidade")),
        migrations.AddField(model_name="organization", name="contact_email", field=models.EmailField(blank=True, max_length=254, verbose_name="e-mail de contato")),
        migrations.AddField(model_name="organization", name="contact_phone", field=models.CharField(blank=True, max_length=30, verbose_name="telefone")),
        migrations.AddField(model_name="organization", name="document", field=models.CharField(blank=True, max_length=18, verbose_name="CNPJ/CPF")),
        migrations.AddField(model_name="organization", name="legal_name", field=models.CharField(blank=True, max_length=200, verbose_name="razao social")),
        migrations.AddField(model_name="organization", name="state", field=models.CharField(blank=True, max_length=2, verbose_name="UF")),
        migrations.AddField(model_name="organization", name="status", field=models.CharField(choices=[("active", "Ativa"), ("suspended", "Suspensa")], default="active", max_length=20, verbose_name="status")),
    ]
