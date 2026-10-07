from django.db import models


class DemoRequest(models.Model):
    class Segment(models.TextChoices):
        ENGINEERING = "engenharia", "Engenharia"
        LEGAL = "juridico", "Jurídico"
        AGRO = "agro", "Agro"
        OTHER = "outro", "Outro"

    name = models.CharField("nome", max_length=120)
    work_email = models.EmailField("e-mail profissional")
    company = models.CharField("empresa", max_length=150)
    segment = models.CharField("segmento", max_length=20, choices=Segment.choices)
    message = models.TextField("mensagem", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "solicitação de demonstração"
        verbose_name_plural = "solicitações de demonstração"

    def __str__(self):
        return f"{self.company} — {self.name}"
