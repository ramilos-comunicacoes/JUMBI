from django.contrib import admin

from .models import DemoRequest


@admin.register(DemoRequest)
class DemoRequestAdmin(admin.ModelAdmin):
    list_display = ("company", "name", "work_email", "segment", "created_at")
    list_filter = ("segment",)
    search_fields = ("company", "name", "work_email")
