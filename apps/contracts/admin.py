from django.contrib import admin
from apps.legal.admin import PlatformReadOnlyAdmin
from .models import Contract, ContractRevision, ContractTemplate

for model in (ContractTemplate, Contract, ContractRevision):
    admin.site.register(model, PlatformReadOnlyAdmin)
