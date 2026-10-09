"""Literal interpolation and private, versioned contract generation."""
import io
import re
import zipfile
from uuid import UUID, uuid4
from xml.sax.saxutils import escape

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max

from apps.billing.services import check_capacity, require_access
from apps.core.models import Membership, Organization
from apps.legal.models import Document
from apps.legal.services import add_document_version, audit, can_write, visible_matters

from .catalog import VARIABLES
from .models import Contract, ContractRevision

PLACEHOLDER = re.compile(r"\[\[([a-z_]+)\]\]")
INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def validate_source(body):
    if not isinstance(body, str) or not body.strip() or len(body) > 100000:
        raise ValidationError("Informe um texto de até 100.000 caracteres.")
    if INVALID_XML.search(body):
        raise ValidationError("O texto contém caracteres de controle inválidos.")
    unknown = sorted(set(PLACEHOLDER.findall(body)) - VARIABLES.keys())
    if unknown:
        raise ValidationError("Variáveis não reconhecidas: " + ", ".join(unknown) + ". Use os botões do catálogo.")
    remainder = PLACEHOLDER.sub("", body)
    if "[[" in remainder or "]]" in remainder:
        raise ValidationError("Revise as variáveis. Use a sintaxe [[cliente_nome]], sem espaços.")


def source_variables(body):
    validate_source(body)
    return list(dict.fromkeys(PLACEHOLDER.findall(body)))


def render_body(body, values):
    required = source_variables(body)
    if not isinstance(values, dict) or set(values) - VARIABLES.keys():
        raise ValidationError("Os campos enviados não pertencem ao catálogo de variáveis.")
    for key, value in values.items():
        if not isinstance(value, str) or len(value) > 8000 or INVALID_XML.search(value):
            raise ValidationError("Informe textos válidos de até 8.000 caracteres nos campos.")
    missing = [VARIABLES[key][0] for key in required if not values.get(key, "").strip()]
    if missing:
        raise ValidationError("Preencha as variáveis usadas no texto: " + "; ".join(missing) + ".")
    # No recursion: values containing placeholder syntax are plain content.
    rendered = PLACEHOLDER.sub(lambda match: values[match[1]].strip(), body)
    if len(rendered) > 200000:
        raise ValidationError("O documento preenchido excede 200.000 caracteres.")
    return rendered


def can_manage_templates(actor, organization):
    return bool(actor.is_active and Membership.objects.filter(
        organization=organization, user=actor, is_active=True,
        organization__status="active", role__in=["owner", "manager"],
    ).exists())


def visible_contracts(actor, organization):
    return Contract.objects.filter(organization=organization, matter__in=visible_matters(actor, organization))


def visible_revisions(actor, organization):
    return ContractRevision.objects.filter(organization=organization, contract__in=visible_contracts(actor, organization))


def make_docx(title, text):
    """Small deterministic OOXML document; no macros, links or embedded HTML."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    def paragraph(value, heading=False):
        style = '<w:pPr><w:pStyle w:val="Title"/></w:pPr>' if heading else ""
        runs = '<w:br/>'.join('<w:t xml:space="preserve">' + escape(line) + '</w:t>' for line in value.split("\n"))
        return f"<w:p>{style}<w:r>{runs}</w:r></w:p>"
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                + paragraph(title, True) + paragraph("RASCUNHO · sujeito à revisão profissional")
                + "".join(paragraph(part) for part in text.split("\n\n"))
                + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>')
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": document,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            entry = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content.encode("utf-8"))
    return output.getvalue()


def generate_revision(*, actor, organization, template, matter, client, title, source_body, values, contract=None, operation_key=None):
    """Lock office before contract/document, matching the global quota lock order."""
    require_access(organization, advanced=True)
    if not can_write(actor, organization):
        raise PermissionDenied("Seu perfil permite somente consulta.")
    if not visible_matters(actor, organization).filter(pk=matter.pk).exists():
        raise PermissionDenied("Você não tem acesso à pasta vinculada.")
    if client.organization_id != organization.pk or (matter.client_id and matter.client_id != client.pk):
        raise ValidationError("O contratante deve ser o cliente da pasta, no mesmo escritório.")
    if template.organization_id != organization.pk or (not contract and not template.is_active):
        raise PermissionDenied("Modelo indisponível para este escritório.")
    if not isinstance(title, str) or not title.strip() or len(title) > 220 or INVALID_XML.search(title):
        raise ValidationError("Informe um título válido de até 220 caracteres.")
    rendered = render_body(source_body, values)
    try:
        operation_key = UUID(str(operation_key)) if operation_key else uuid4()
    except (ValueError, TypeError, AttributeError) as error:
        raise ValidationError("Identificador de operação inválido.") from error
    version = None
    try:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization.pk)
            existing = ContractRevision.objects.filter(operation_key=operation_key).select_related("contract").first()
            if existing:
                if (existing.organization_id != organization.pk or existing.created_by_id != actor.pk
                        or existing.title != title.strip() or existing.source_body != source_body or existing.values != values
                        or (existing.contract.matter_id, existing.contract.client_id, existing.contract.template_id) != (matter.pk, client.pk, template.pk)
                        or (contract and existing.contract_id != contract.pk)):
                    raise ValidationError("Esta operação já foi utilizada para outra versão. Recarregue a montagem.")
                return existing
            check_capacity(organization, "versions")
            if contract:
                contract = Contract.objects.select_for_update().get(pk=contract.pk, organization=organization)
                if (contract.matter_id, contract.client_id, contract.template_id) != (matter.pk, client.pk, template.pk):
                    raise ValidationError("Os vínculos do contrato devem ser preservados.")
                contract.title = title.strip()
                contract.save(update_fields=["title"])
            else:
                document = Document.objects.create(
                    organization=organization, matter=matter, title=title.strip(), kind="Contrato · rascunho", created_by=actor,
                )
                contract = Contract.objects.create(
                    organization=organization, matter=matter, client=client, template=template,
                    document=document, title=title.strip(), created_by=actor,
                )
            number = (contract.revisions.aggregate(maximum=Max("number"))["maximum"] or 0) + 1
            version = add_document_version(
                document=contract.document, actor=actor,
                file=ContentFile(make_docx(title.strip(), rendered), name=f"contrato-{contract.pk}-v{number}.docx"),
            )
            revision = ContractRevision.objects.create(
                organization=organization, contract=contract, document_version=version, number=number,
                title=title.strip(), template_name=template.name, source_body=source_body,
                values=values, rendered_text=rendered, created_by=actor,
                operation_key=operation_key,
            )
            audit(organization=organization, actor=actor, action="contract.generated", obj=revision,
                  description=f"Rascunho v{number} preservado na pasta; SHA-256 {revision.checksum}.")
            return revision
    except Exception:
        if version is not None and version.file:
            version.file.storage.delete(version.file.name)
        raise
