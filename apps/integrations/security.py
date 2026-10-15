"""Cryptographic and input security primitives for JUMBI Judicial Integrations.

Guards:
- Strict SSRF prevention and destination allowlist checking
- Constant-time HMAC-SHA256 signature verification over raw request body
- Deterministic canonical payload hashing for internal idempotency enforcement
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import socket
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit
from django.core.cache import cache


class IntegrationSecurityError(ValueError):
    pass


# Officially documented public hostnames approved for external calls
APPROVED_HOSTS = {
    "comunicaapi.pje.jus.br",
    "hcomunicaapi.cnj.jus.br",
    "comunica.pje.jus.br",
    "pje1g-mni.tjba.jus.br",
    "pje2g-mni.tjba.jus.br",
    "www12.tjrj.jus.br",
    "www3.tjrj.jus.br",
    "sso.cloud.pje.jus.br",
    "sso.stg.cloud.pje.jus.br",
    "gateway.stg.cloud.pje.jus.br",
    "domicilio-eletronico.pdpj.jus.br",
    "portalexterno-tribunais.stg.pdpj.jus.br",
}


def verify_pdpj_signature(
    body: bytes | None = None,
    signature: str | None = None,
    secret: bytes | str = b"",
    *,
    raw_body: bytes | None = None
) -> bool:
    """Verify HMAC-SHA256 signature over raw request body in constant time.
    
    Source: CNJ PDPJ Webhooks specification (A07).
    """
    actual_body = body if body is not None else raw_body
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not isinstance(actual_body, bytes) or not isinstance(secret, bytes) or not secret:
        return False
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
        return False
    expected = hmac.new(secret, actual_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def is_private_or_reserved_ip(ip_str: str) -> bool:
    """Check whether an IP address belongs to loopback, private, link-local or reserved ranges."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return True


def validate_allowed_url(url: str, allowed_hosts: set[str] | None = None, check_dns: bool = False) -> str:
    """Validate that target URL uses HTTPS, default port 443, has no credentials,
    and points to an approved judicial destination.
    """
    hosts = allowed_hosts or APPROVED_HOSTS
    if not isinstance(url, str) or not url or any(ord(c) <= 32 for c in url) or "\\" in url:
        raise IntegrationSecurityError("URL inválida ou malformada.")

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise IntegrationSecurityError("Porta ou URL inválida.") from exc

    if parts.scheme != "https":
        raise IntegrationSecurityError("Exigido protocolo HTTPS seguro.")

    if parts.username is not None or parts.password is not None:
        raise IntegrationSecurityError("Credenciais na URL são expressamente proibidas.")

    if port not in (None, 443) or parts.fragment:
        raise IntegrationSecurityError("Porta não padrão ou fragmentos não permitidos.")

    hostname = (parts.hostname or "").lower()
    if not hostname or hostname not in {h.lower() for h in hosts}:
        raise IntegrationSecurityError(f"Destino '{hostname}' fora da lista de servidores aprovados.")

    if check_dns:
        try:
            addr_info = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
            for _, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                if is_private_or_reserved_ip(ip_str):
                    raise IntegrationSecurityError(f"Endereço IP resolvido '{ip_str}' está em faixa privada/reservada (bloqueio SSRF).")
        except socket.gaierror as exc:
            raise IntegrationSecurityError(f"Falha de resolução DNS para {hostname}: {exc}") from exc

    return url


def canonical_request_hash(payload: Mapping) -> str:
    """Calculate deterministic SHA-256 hash for internal command idempotency."""
    try:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise IntegrationSecurityError("Payload não representável em JSON canônico.") from exc
    return hashlib.sha256(data).hexdigest()


def check_idempotency_conflict(
    previous_hash: str | None = None,
    payload: Mapping | None = None,
    *,
    organization: Any = None,
    key: str | None = None,
    path: str = "",
    method: str = "POST",
    ttl_seconds: int = 86400,
) -> bool | None:
    """Verify if the same idempotency key is being reused with different content.
    
    Supports:
    1. Direct previous_hash comparison: check_idempotency_conflict(prev_hash, payload) -> raises if conflict
    2. Cache-backed check: check_idempotency_conflict(organization=org, key=key, path=path, method=method, payload=payload) -> bool
    """
    if previous_hash is not None and key is None:
        current_hash = canonical_request_hash(payload or {})
        if not hmac.compare_digest(previous_hash, current_hash):
            raise IntegrationSecurityError("IDEMPOTENCY_CONFLICT: chave de idempotência repetida com corpo de requisição diferente.")
        return None

    org_id = getattr(organization, "pk", organization) or "global"
    cache_key = f"idemp:{org_id}:{path}:{key}"
    curr_hash = canonical_request_hash(payload or {})

    stored_hash = cache.get(cache_key)
    if stored_hash is None:
        cache.set(cache_key, curr_hash, timeout=ttl_seconds)
        return False

    if not hmac.compare_digest(stored_hash, curr_hash):
        return True  # Conflict detected!
    return False
