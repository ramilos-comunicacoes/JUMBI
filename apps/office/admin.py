from django.contrib import admin

from .models import (
    Client,
    LegalCase,
    LegalDocument,
    MatterType,
    OfficeFinanceEntry,
    OfficePurchase,
    PracticeArea,
    StaffMember,
    WorkItem,
)

admin.site.register(PracticeArea)
admin.site.register(MatterType)
admin.site.register(Client)
admin.site.register(WorkItem)
admin.site.register(StaffMember)
admin.site.register(LegalCase)
admin.site.register(LegalDocument)
admin.site.register(OfficeFinanceEntry)
admin.site.register(OfficePurchase)
