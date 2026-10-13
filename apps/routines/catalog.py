"""Operational examples only. Firms review documents and legal obligations."""

EXAMPLES = {
    "acolhimento": {
        "title": "Primeiro atendimento", "niches": [],
        "description": "Organize o início do atendimento e confirme com a equipe o que é necessário para esta demanda.",
        "tasks": ["Registrar relato e objetivo do atendimento", "Revisar documentos recebidos", "Definir o próximo contato com o cliente"],
        "checklist": ["Conferir cadastro e canal de contato", "Verificar conflito de interesses", "Revisar escopo e honorários com o cliente"],
        "documents": ["Documento de identificação, quando necessário", "Documentos relacionados à demanda"],
    },
    "familia": {
        "title": "Organização de demanda familiar", "niches": ["familia"],
        "description": "Roteiro de organização inicial. Avalie individualmente a necessidade e a pertinência de cada documento.",
        "tasks": ["Registrar contexto familiar e objetivo", "Revisar informações patrimoniais pertinentes", "Preparar reunião de orientação"],
        "checklist": ["Revisar acesso e sigilo da pasta", "Conferir informações das partes"],
        "documents": ["Certidões pertinentes à demanda", "Comprovantes relevantes ao caso"],
    },
    "trabalhista": {
        "title": "Organização de demanda trabalhista", "niches": ["trabalhista"],
        "description": "Organize os fatos, os vínculos e os arquivos antes da análise jurídica da equipe.",
        "tasks": ["Registrar histórico do vínculo", "Organizar fatos e evidências recebidas", "Agendar revisão jurídica da demanda"],
        "checklist": ["Conferir datas e vínculos informados", "Conferir documentos legíveis e completos"],
        "documents": ["Documentos do vínculo disponíveis", "Comprovantes de pagamentos pertinentes"],
    },
    "previdenciario": {
        "title": "Organização de demanda previdenciária", "niches": ["previdenciario"],
        "description": "Prepare a documentação para análise humana das condições e possibilidades do atendimento.",
        "tasks": ["Registrar objetivo e histórico do atendimento", "Organizar histórico de contribuições recebido", "Preparar análise documental pela equipe"],
        "checklist": ["Conferir identificação e contatos", "Registrar pendências documentais"],
        "documents": ["Extratos e comprovantes pertinentes", "Documentos de requerimentos anteriores, se existentes"],
    },
    "consumidor": {
        "title": "Organização de demanda de consumo", "niches": ["consumidor", "civil"],
        "description": "Centralize as informações da relação de consumo e das tentativas anteriores de solução.",
        "tasks": ["Registrar cronologia dos fatos", "Organizar tentativas de atendimento anteriores", "Revisar material com o responsável"],
        "checklist": ["Identificar fornecedores envolvidos", "Conferir valores e comprovantes apresentados"],
        "documents": ["Contrato, pedido ou nota fiscal disponível", "Protocolos e comunicações com o fornecedor"],
    },
}
