"""Primitivas testáveis, sem rede e sem dependência de Django.
A validação de URL abaixo cobre somente forma/allowlist; a aplicação deve acrescentar validação de DNS/IP e controle de egress contra SSRF.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit


class IntegrationInputError(ValueError):
    pass


def verify_pdpj_signature(body: bytes, signature: str | None, secret: bytes) -> bool:
    """HMAC-SHA256 hexadecimal do corpo ORIGINAL. Fonte: A07."""
    if not isinstance(body, bytes) or not isinstance(secret, bytes) or not secret:
        return False
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
        return False
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def validate_allowed_url(url: str, allowed_hosts: set[str]) -> str:
    """Não segue redirecionamento e não resolve imports; apenas valida a URL."""
    if not isinstance(url, str) or not url or any(ord(c) <= 32 for c in url) or "\\" in url:
        raise IntegrationInputError("URL inválida")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise IntegrationInputError("Porta/URL inválida") from exc
    if parts.scheme != "https" or parts.username is not None or parts.password is not None:
        raise IntegrationInputError("Exigir HTTPS sem credenciais na URL")
    if port not in (None, 443) or parts.fragment:
        raise IntegrationInputError("Porta ou fragmento não permitido")
    if not parts.hostname or parts.hostname.lower() not in {h.lower() for h in allowed_hosts}:
        raise IntegrationInputError("Destino fora da lista aprovada")
    return url


def canonical_request_hash(payload: Mapping) -> str:
    """Apenas para idempotência INTERNA; não usar para validar webhook."""
    try:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise IntegrationInputError("Payload não representável em JSON canônico") from exc
    return hashlib.sha256(data).hexdigest()


def check_reused_key(previous_hash: str, payload: Mapping) -> None:
    if not hmac.compare_digest(previous_hash, canonical_request_hash(payload)):
        raise IntegrationInputError("IDEMPOTENCY_CONFLICT: chave repetida com corpo diferente")
