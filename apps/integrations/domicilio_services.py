"""Domicílio adapter intentionally unavailable until official homologation."""
from django.core.exceptions import PermissionDenied, ValidationError

class DomicilioJudicialService:
    def __init__(self, organization):
        self.organization = organization

    def list_pending_notices(self):
        raise ValidationError("Consulta ao Domicílio não homologada. Consulte a fonte oficial.")

    def request_open_content(self, notice_id, actor, grant):
        if not grant or not grant.is_valid() or grant.organization_id != self.organization.pk or grant.grantee_id != actor.pk:
            raise PermissionDenied("Outorga válida e específica obrigatória.")
        raise ValidationError("Abertura oficial e ciência processual não homologadas nesta versão.")
