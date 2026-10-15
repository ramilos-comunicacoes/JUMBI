import json
from pathlib import Path
from django.db import migrations

INVENTORY_FILE = Path(__file__).resolve().parents[3] / "integrations_v2" / "03_REGISTRO_TRIBUNAIS.json"

STANDARD_PROVIDERS = [
    {
        "code": "djen",
        "name": "Diário de Justiça Eletrônico Nacional (CNJ / Comunica PJe)",
        "documentation_status": "documented",
        "authorization_status": "public_read_documented",
        "capabilities": ["publications", "certificates", "issues"],
        "policy": "Leitura pública permitida com respeito a limites de requisição e cabeçalhos de rate limit.",
    },
    {
        "code": "mni",
        "name": "Modelo Nacional de Interoperabilidade (SOAP / WSDL)",
        "documentation_status": "documented",
        "authorization_status": "per_instance_authorization_required",
        "capabilities": ["case_data", "movements", "pending_notices", "documents", "filing"],
        "policy": "Exige habilitação e WSDL validado por tribunal/instância. Sem chamadas com DTD ou entidades externas.",
    },
    {
        "code": "domicilio",
        "name": "Domicílio Judicial Eletrônico (PDPJ / CNJ)",
        "documentation_status": "documented",
        "authorization_status": "awaiting_credentials_contract_and_authorization",
        "capabilities": ["personal_communications", "acknowledgment", "logs"],
        "policy": "Acesso institucional por CNPJ. Abertura oficial gera ciência jurídica e exige autorização explícita.",
    },
    {
        "code": "pdpj_webhooks",
        "name": "Notificações e Webhooks PDPJ",
        "documentation_status": "documented",
        "authorization_status": "requires_authorized_subscription",
        "capabilities": ["event_notifications"],
        "policy": "Exige assinatura HMAC-SHA256 validada sobre o corpo bruto original.",
    },
    {
        "code": "tjrj_reference",
        "name": "TJRJ — Metadados de Comarcas e Órgãos",
        "documentation_status": "documented",
        "authorization_status": "public_read_documented",
        "capabilities": ["reference_data"],
        "policy": "Dados cadastrais públicos de serventias e comarcas.",
    },
    {
        "code": "tpu",
        "name": "Tabelas Processuais Unificadas (TPU)",
        "documentation_status": "documented",
        "authorization_status": "public_read_documented",
        "capabilities": ["reference_tables"],
        "policy": "Tabelas oficiais de classes, assuntos e movimentos processuais.",
    },
    {
        "code": "bnp_optional",
        "name": "Banco Nacional de Precedentes (Pangea / BNP)",
        "documentation_status": "documented",
        "authorization_status": "authorization_required",
        "capabilities": ["precedents"],
        "policy": "Consulta autenticada de repetitivos e precedentes vinculantes.",
    },
    {
        "code": "cnj_consolidated_data",
        "name": "Dados Consolidados CNJ (Res. 574/2024 e Portaria 442/2026)",
        "documentation_status": "documented",
        "authorization_status": "requires_institutional_application_and_possible_costs",
        "capabilities": ["consolidated_data"],
        "policy": "Sujeito a convênio formal com o CNJ e processo de habilitação de integridade.",
    },
    {
        "code": "datajud",
        "name": "DataJud",
        "documentation_status": "documented",
        "authorization_status": "blocked_for_commercial_use_pending_formal_review",
        "capabilities": [],
        "policy": "Bloqueado para uso comercial conforme restrição expressa da Portaria CNJ 374/2026.",
    },
    {
        "code": "previdia_inss",
        "name": "Previdia / Requerimentos INSS",
        "documentation_status": "awaiting_contract",
        "authorization_status": "manual_authorized_import",
        "capabilities": ["administrative_demands"],
        "policy": "Importação manual de protocolos e despachos sem compartilhamento indevido de senhas.",
    },
]

STANDARD_CAPABILITIES = [
    "publications",
    "case_data",
    "movements",
    "documents",
    "personal_communications",
    "formal_notice",
    "filing",
]


def populate_inventory(apps, schema_editor):
    IntegrationProvider = apps.get_model("integrations", "IntegrationProvider")
    SourceDeployment = apps.get_model("integrations", "SourceDeployment")
    IntegrationCapability = apps.get_model("integrations", "IntegrationCapability")

    # 1. Provedores
    for p_data in STANDARD_PROVIDERS:
        IntegrationProvider.objects.update_or_create(
            code=p_data["code"],
            defaults={
                "name": p_data["name"],
                "documentation_status": p_data["documentation_status"],
                "authorization_status": p_data["authorization_status"],
                "capabilities": p_data["capabilities"],
                "policy": p_data["policy"],
            },
        )

    # 2. Tribunais do 03_REGISTRO_TRIBUNAIS.json
    if INVENTORY_FILE.exists():
        data = json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
    else:
        entries = []

    for item in entries:
        tribunal = item["tribunal"]
        branch = item.get("branch", "estadual")
        uf = item.get("uf")
        system = item.get("systems_from_v1", "PJe")
        notes = item.get("note_from_v1", "")

        deployment, _ = SourceDeployment.objects.update_or_create(
            tribunal=tribunal,
            branch=branch,
            grade="geral",
            environment="production",
            defaults={
                "uf": uf,
                "system": system,
                "inventory_status": "inherited_documentary_not_reverified_v2",
                "live_integration": False,
                "djen_capability": "national_source_requires_filter_and_coverage_validation",
                "notes": notes,
            },
        )

        for cap in STANDARD_CAPABILITIES:
            IntegrationCapability.objects.update_or_create(
                deployment=deployment,
                capability=cap,
                defaults={
                    "documentation_status": "DOCUMENTED" if cap == "publications" else "AWAITING_WSDL_CONTRACT",
                    "authorization_status": "PENDING_CREDENTIALS",
                    "health_status": "NOT_HOMOLOGATED",
                },
            )


def rollback_inventory(apps, schema_editor):
    IntegrationProvider = apps.get_model("integrations", "IntegrationProvider")
    SourceDeployment = apps.get_model("integrations", "SourceDeployment")
    IntegrationCapability = apps.get_model("integrations", "IntegrationCapability")

    IntegrationCapability.objects.all().delete()
    SourceDeployment.objects.all().delete()
    IntegrationProvider.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(populate_inventory, rollback_inventory),
    ]
