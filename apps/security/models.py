from django.conf import settings
from django.db import models


class AccountSecurity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    secret_ciphertext = models.TextField(blank=True)
    enabled = models.BooleanField(default=False)
    last_counter = models.BigIntegerField(default=-1)
    recovery_hashes = models.JSONField(default=list)
    session_epoch = models.PositiveIntegerField(default=0)
    failures = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    password_failures = models.PositiveIntegerField(default=0)
    password_locked_until = models.DateTimeField(null=True, blank=True)


class SecurityEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
