from django.conf import settings
from django.contrib import admin

from .models import AgroFinanceEntry, AgroPurchase, Farm, FarmOperation, Field, InventoryItem, StaffMember, Supplier

if not settings.JUMBI_LEGAL_ONLY:
    admin.site.register(Farm)
    admin.site.register(Field)
    admin.site.register(StaffMember)
    admin.site.register(Supplier)
    admin.site.register(InventoryItem)
    admin.site.register(FarmOperation)
    admin.site.register(AgroFinanceEntry)
    admin.site.register(AgroPurchase)
