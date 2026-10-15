"""Inspeciona OpenAPI JSON/YAML ou WSDL local. Não faz chamadas de negócio.
Uso: python -m tools.contract_inspector contrato.yml --out perfil.json
Schemas/refs remotos não são baixados. A saída é sempre draft, nunca homologada.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

MAX_BYTES = 4 * 1024 * 1024


class ContractError(ValueError):
    pass


def local_ref(document: dict, value: Any) -> Any:
    visited: set[str] = set()
    for _ in range(32):
        if not isinstance(value, dict) or "$ref" not in value:
            return value
        ref = value["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            raise ContractError("Referência externa: obter e aprovar separadamente")
        if ref in visited:
            raise ContractError("Referência circular")
        visited.add(ref)
        value = document
        for item in ref[2:].split("/"):
            key = item.replace("~1", "/").replace("~0", "~")
            try:
                value = value[key]
            except (KeyError, TypeError) as exc:
                raise ContractError(f"Referência local inexistente: {ref}") from exc
    raise ContractError("Limite de referências excedido")


def inspect_openapi(document: dict) -> dict:
    if not isinstance(document, dict) or not (document.get("openapi") or document.get("swagger")):
        raise ContractError("Não é OpenAPI/Swagger")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise ContractError("OpenAPI sem paths válidos")
    result = {
        "status": "draft",
        "format": "openapi",
        "version": document.get("openapi", document.get("swagger")),
        "info": document.get("info", {}),
        "servers": document.get("servers", []),
        "swagger_host": document.get("host"),
        "swagger_basePath": document.get("basePath"),
        "operations": [],
    }
    for path, raw_entry in paths.items():
        entry = local_ref(document, raw_entry)
        if not isinstance(entry, dict):
            raise ContractError("Path inválido")
        for method in ("get", "post", "put", "patch", "delete", "head", "options", "trace"):
            if method not in entry:
                continue
            op = local_ref(document, entry[method])
            if not isinstance(op, dict):
                raise ContractError("Operação inválida")
            merged = {}
            for raw_p in entry.get("parameters", []) + op.get("parameters", []):
                p = local_ref(document, raw_p)
                if not isinstance(p, dict) or "name" not in p or "in" not in p:
                    raise ContractError("Parâmetro inválido")
                merged[(p["in"], p["name"])] = {
                    "name": p["name"],
                    "in": p["in"],
                    "required": p.get("required", False),
                    "schema": p.get("schema", {k: p[k] for k in ("type", "format", "enum", "minimum", "maximum") if k in p}),
                }
            result["operations"].append({
                "method": method.upper(),
                "path": path,
                "operationId": op.get("operationId"),
                "parameters": list(merged.values()),
                "security": op.get("security", document.get("security", [])),
                "responses": op.get("responses", {}),
                "requestBody": op.get("requestBody"),
            })
    return result


def inspect_wsdl(raw: bytes) -> dict:
    try:
        from defusedxml import ElementTree as ET
    except ImportError as exc:
        raise ContractError("Instale requirements-tools.txt para leitura segura de XML") from exc
    try:
        root = ET.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception as exc:
        raise ContractError("XML inválido ou com entidades/DTD proibidos") from exc
    tag = root.tag.split("}")[-1]
    if tag not in {"definitions", "description"}:
        raise ContractError("XML não identificado como WSDL")
    operations = set()
    imports = set()
    addresses = set()
    for e in root.iter():
        local = e.tag.split("}")[-1]
        if local == "operation" and e.get("name"):
            operations.add(e.get("name"))
        if local in {"import", "include"}:
            location = e.get("location") or e.get("schemaLocation")
            if location:
                imports.add(location)
        if local in {"address", "endpoint"}:
            location = e.get("location") or e.get("address")
            if location:
                addresses.add(location)
    return {
        "status": "draft",
        "format": "wsdl",
        "targetNamespace": root.get("targetNamespace"),
        "operations": sorted(operations),
        "imports_NOT_FETCHED": sorted(imports),
        "addresses_NOT_CALLED": sorted(addresses),
    }


def inspect_file(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ContractError("Arquivo ausente ou excede limite de 4 MiB")
    raw = path.read_bytes()
    if not raw.strip():
        raise ContractError("Contrato vazio")
    if raw.lstrip().startswith(b"<"):
        report = inspect_wsdl(raw)
    else:
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                import yaml
                document = yaml.safe_load(raw)
            except Exception as exc:
                raise ContractError("Não foi possível interpretar JSON/YAML seguro") from exc
        report = inspect_openapi(document)
    report["source_file"] = path.name
    report["sha256"] = hashlib.sha256(raw).hexdigest()
    report["size_bytes"] = len(raw)
    report["production_approved"] = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_file(args.contract)
    except ContractError as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False))
        return 2
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
