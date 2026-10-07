from django.conf import settings
from django.contrib import admin

from .models import Employee, FinanceEntry, Project, ProjectEvidence, ProjectTask, Purchase, Supplier

if not settings.JUMBI_LEGAL_ONLY:
    admin.site.register(Project)
    admin.site.register(Supplier)
    admin.site.register(ProjectTask)
    admin.site.register(ProjectEvidence)
    admin.site.register(Employee)
    admin.site.register(FinanceEntry)
    admin.site.register(Purchase)
