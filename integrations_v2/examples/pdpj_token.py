"""Exemplo SSO institucional. Nenhuma credencial está incluída.
Uso a partir da raiz do pacote:
PDPJ_ENVIRONMENT=sandbox python -m examples.pdpj_token
PDPJ_CLIENT_ID e PDPJ_CLIENT_SECRET devem vir do ambiente protegido.
A execução direta nunca imprime o token. Para integrá-lo, use obtain_token().
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlencode
from urllib.request import Request
from tools.doctor_integrations import make_opener

TOKEN_URLS = {
    "sandbox": "https://sso.stg.cloud.pje.jus.br/auth/realms/pje/protocol/openid-connect/token",
    "production": "https://sso.cloud.pje.jus.br/auth/realms/pje/protocol/openid-connect/token",
}


@dataclass(frozen=True)
class ServiceToken:
    access_token: str = field(repr=False)
    token_type: str
    expires_in: int


class TokenError(RuntimeError):
    pass


def obtain_token(environment: str, client_id: str, client_secret: str) -> ServiceToken:
    if environment not in TOKEN_URLS or not client_id or not client_secret:
        raise TokenError("Ambiente/credencial não configurado")
    body = urlencode({"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}).encode()
    request = Request(
        TOKEN_URLS[environment],
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with make_opener().open(request, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise TokenError("Resposta excede limite")
            result = json.loads(raw)
    except Exception as exc:
        raise TokenError(f"Falha no SSO ({type(exc).__name__}); verificar acesso no ambiente correto") from None
    token = result.get("access_token") if isinstance(result, dict) else None
    expires = result.get("expires_in") if isinstance(result, dict) else None
    kind = result.get("token_type", "") if isinstance(result, dict) else ""
    if not isinstance(token, str) or not token or not isinstance(kind, str) or kind.lower() != "bearer" or not isinstance(expires, int) or isinstance(expires, bool) or expires <= 0:
        raise TokenError("Resposta de token inválida")
    return ServiceToken(access_token=token, token_type=kind, expires_in=expires)


def main() -> int:
    try:
        token = obtain_token(os.getenv("PDPJ_ENVIRONMENT", "sandbox"), os.getenv("PDPJ_CLIENT_ID", ""), os.getenv("PDPJ_CLIENT_SECRET", ""))
    except TokenError as exc:
        print(json.dumps({"authenticated": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"authenticated": True, "token_type": token.token_type, "expires_in": token.expires_in, "token_not_printed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
