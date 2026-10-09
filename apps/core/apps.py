from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self):
        from django.contrib import admin

        # AdminConfig runs autodiscovery before CoreConfig.ready. Keep legacy
        # apps installed for migrations/data, but never expose their admin URLs.
        allowed_labels = {"auth", "core", "legal", "billing", "contracts", "performance"}
        for model in tuple(admin.site._registry):
            if model._meta.app_label not in allowed_labels:
                admin.site.unregister(model)
