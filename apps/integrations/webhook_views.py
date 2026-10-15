"""PDPJ Webhook Receiver with HMAC-SHA256 Signature Verification.

Accepts signed payloads from CNJ / PDPJ and stores them securely in WebhookInbox.
"""
import hashlib
import json
import logging
import uuid
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import WebhookInbox
from .security import verify_pdpj_signature

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def receive_pdpj_webhook(request, subscription_id):
    """Receive and securely verify PDPJ webhook notification."""
    raw_body = request.body
    signature = request.headers.get("X-PDPJ-Webhook-Signature", "")

    # Retrieve subscription webhook secret
    secret = getattr(settings, "PDPJ_WEBHOOK_SECRET", "jumbi_pdpj_secret_2026")

    # Verify signature over raw bytes
    is_valid = verify_pdpj_signature(raw_body=raw_body, signature=signature, secret=secret)
    if not is_valid:
        logger.warning("PDPJ Webhook signature verification failed for subscription %s", subscription_id)
        return JsonResponse({
            "code": "UNAUTHORIZED_SIGNATURE",
            "message": "Assinatura do webhook inválida ou ausente.",
            "correlation_id": str(uuid.uuid4())
        }, status=401)

    # Compute deduplication payload hash
    payload_hash = hashlib.sha256(raw_body).hexdigest()

    # Check duplicate
    existing = WebhookInbox.objects.filter(payload_hash=payload_hash).first()
    if existing:
        return JsonResponse({"received": True, "duplicate": True}, status=202)

    try:
        data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        data = {"raw": raw_body.decode("utf-8", errors="replace")}

    # Persist in WebhookInbox
    WebhookInbox.objects.create(
        subscription_id=subscription_id,
        payload_hash=payload_hash,
        headers=dict(request.headers),
        body=data,
        is_valid_signature=True,
    )

    return JsonResponse({"received": True, "duplicate": False}, status=202)
