"""Personal saved searches contain criteria, never cached legal records."""
from django.conf import settings
from django.db import models


class SavedSearch(models.Model):
    organization = models.ForeignKey("core.Organization", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=60)
    query = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, blank=True)
    niche = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [models.UniqueConstraint(fields=["organization", "user", "name"], name="discovery_unique_personal_name")]
