"""Diagnóstico pontual de metadados/contratos públicos, sem dados de pessoas.
Por padrão, apenas mostra o alvo. Uma única requisição exige --online.
Não autentica, não abre comunicações pessoais e não tenta contornar bloqueios.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .security_primitives import validate_allowed_url

TARGETS = {
    "djen-tribunais": "https://comunicaapi.pje.jus.br/api/v1/comunicacao/tribunal",
    "djen-yaml": "https://hcomunicaapi.cnj.jus.br/swagger/djen.yml",
    "tjba-1g-wsdl": "https://pje1g-mni.tjba.jus.br/pje/intercomunicacao?wsdl",
    "tjba-2g-wsdl": "https://pje2g-mni.tjba.jus.br/pje/intercomunicacao?wsdl",
    "tjba-1g-catalogo": "https://pje1g-mni.tjba.jus.br/pje/ConsultaPJe?wsdl",
    "tjba-2g-catalogo": "https://pje2g-mni.tjba.jus.br/pje/ConsultaPJe?wsdl",
    "tjrj-comarcas": "https://www3.tjrj.jus.br/orgaoservicepub/api/ServicoPub/Comarca",
    "tjrj-orgaos": "https://www3.tjrj.jus.br/orgaoservicepub/api/ServicoPub/Orgao",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )


def atomic_private_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".jumbi-", dir=path.parent)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def fetch_target(name: str, output: Path, timeout: float = 20) -> dict:
    url = TARGETS[name]
    validate_allowed_url(url, {urlsplit(u).hostname for u in TARGETS.values()})
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Jumbi-Contract-Doctor/2.0",
            "Accept": "application/json, application/yaml, text/yaml, application/xml, text/xml",
        },
    )
    try:
        with make_opener().open(request, timeout=timeout) as response:
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                return {"target": name, "status": "too_large", "saved": False}
            content_type = response.headers.get("Content-Type", "")
            if not body.strip() or "text/html" in content_type.lower() or body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                return {"target": name, "status": "unexpected_content", "http_status": response.status, "saved": False}
            destination = output / (name + ".raw")
            atomic_private_write(destination, body)
            return {
                "target": name,
                "url": url,
                "status": "fetched_NOT_homologated",
                "http_status": response.status,
                "content_type": content_type,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "file": str(destination),
                "saved": True,
                "rate_limit_headers": {k: v for k, v in response.headers.items() if "ratelimit" in k.lower().replace("-", "") or k.lower() == "retry-after"},
            }
    except urllib.error.HTTPError as exc:
        return {
            "target": name,
            "status": "http_error",
            "http_status": exc.code,
            "saved": False,
            "retry_after": exc.headers.get("Retry-After"),
            "note": "Sem retry automático ou desvio de proteção",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"target": name, "status": "network_error", "error_type": type(exc).__name__, "saved": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(TARGETS), default="djen-tribunais")
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("local-contracts"))
    args = parser.parse_args()
    if not args.online:
        print(json.dumps({"mode": "dry_run", "target": args.target, "url": TARGETS[args.target], "request_count": 0}, ensure_ascii=False, indent=2))
        return 0
    result = fetch_target(args.target, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("saved") else 2


if __name__ == "__main__":
    raise SystemExit(main())
