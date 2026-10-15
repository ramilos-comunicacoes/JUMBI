"""Signed, tenant-bound inbox. Acceptance does not mean processing or official notice."""
import hashlib
import json
from django.http import JsonResponse
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from cryptography.fernet import InvalidToken
from .credentials import decrypt_credentials
from .models import IntegrationAccount, WebhookInbox
from .security import verify_pdpj_signature


@csrf_exempt
@require_POST
def receive_pdpj_webhook(request, subscription_id):
    account = IntegrationAccount.objects.filter(pk=subscription_id, provider__code="pdpj-webhook", enabled=True,
        revoked_at__isnull=True, organization__status="active").first()
    if not account or not account.has_credentials:
        return JsonResponse({"code": "NOT_CONFIGURED"}, status=503)
    try:
        secret = decrypt_credentials(account.encrypted_credentials).get("webhook_secret", "")
    except (ValueError, InvalidToken):
        secret = ""
    raw = request.body
    if len(raw) > 1024 * 1024:
        return JsonResponse({"code": "PAYLOAD_TOO_LARGE"}, status=413)
    signature = request.headers.get("X-PDPJ-Webhook-Signature", "")
    if not verify_pdpj_signature(raw_body=raw, signature=signature, secret=secret):
        return JsonResponse({"code": "UNAUTHORIZED_SIGNATURE"}, status=401)
    try:
        body = json.loads(raw.decode())
        event_id = body.get("id") or body.get("event_id") if isinstance(body, dict) else None
        if not isinstance(event_id, (str, int)) or not 1 <= len(str(event_id)) <= 150:
            raise ValueError()
    except (ValueError, UnicodeError):
        return JsonResponse({"code": "INVALID_EVENT"}, status=400)
    digest = hashlib.sha256(raw).hexdigest()
    with transaction.atomic():
        item, created = WebhookInbox.objects.get_or_create(organization=account.organization,
            subscription_id=subscription_id, external_event_id=str(event_id), defaults={
                "payload_hash": digest, "signature_received": signature, "raw_bytes": raw, "parsed_payload": body})
        if item.payload_hash != digest:
            return JsonResponse({"code": "EVENT_CONFLICT"}, status=409)
    return JsonResponse({"received": True, "duplicate": not created, "processed": False}, status=202)
