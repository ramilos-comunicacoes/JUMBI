"""Domicílio Judicial Eletrônico Integration Service.

Guards access to electronic judicial summons and notices.
Crucial legal safeguard: listing pending notices is safe, but OPENING a notice
(request_open_content) triggers legal acknowledgment ('ciência tácita/expressa')
starting judicial deadlines. Therefore, opening requires explicit AuthorizationGrant.
"""
import logging
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.legal.services import audit
from .models import AuthorizationGrant, ExternalOperation

logger = logging.getLogger(__name__)


class DomicilioJudicialService:
    """Safe integration service for Domicílio Judicial Eletrônico."""

    def __init__(self, organization):
        self.organization = organization

    def list_pending_notices(self):
        """List incoming notices safely WITHOUT triggering acknowledgment."""
        # Operational simulated response with complete contract structure
        return [
            {
                "id_aviso": "DOM-2026-00412",
                "tribunal": "TRF1",
                "tipo": "Intimação Eletrônica",
                "data_disponibilizacao": timezone.now().strftime("%Y-%m-%d"),
                "prazo_ciencia_limite": (timezone.now() + timezone.timedelta(days=10)).strftime("%Y-%m-%d"),
                "status": "pendente_abertura",
                "requires_authorization": True,
            }
        ]

    def request_open_content(self, notice_id: str, actor, grant: AuthorizationGrant):
        """Open communication content - REQUIRES SIGNED AUTHORIZATION GRANT."""
        if not grant or not grant.is_valid():
            raise PermissionDenied(
                "Abertura de intimação no Domicílio Judicial Eletrônico requer concessão formal de poderes "
                "(AuthorizationGrant) ativa e válida para evitar ciência involuntária de prazos processuais."
            )

        if grant.organization != self.organization:
            raise PermissionDenied("Concessão pertence a outro escritório.")

        # Record operation
        operation = ExternalOperation.objects.create(
            organization=self.organization,
            deployment=None,
            action="domicilio.open_notice",
            actor=actor,
            authorization_grant=grant,
            payload_summary={"notice_id": notice_id, "grant_id": grant.pk},
            status=ExternalOperation.Status.SUCCESS,
            response_summary={"opened_at": timezone.now().isoformat(), "science_registered": False},
        )

        audit(
            organization=self.organization,
            actor=actor,
            action="integrations.domicilio_notice_opened",
            description=f"Aviso {notice_id} do Domicílio Judicial aberto com base na outorga #{grant.pk}."
        )

        return {
            "status": "opened",
            "notice_id": notice_id,
            "operation_id": operation.pk,
            "content": f"Conteúdo do aviso {notice_id} liberado sob outorga assinada por {grant.granted_by.email}.",
        }
