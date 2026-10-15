JUMBI — Pacote de implementação de integrações para o Codex
Versão 2.0 • 14/10/2026 • Destino previsto: jumbi.nabio.pro

Uso
Extraia a pasta do ZIP no ambiente de trabalho do Codex ou anexe seus arquivos. Cole o conteúdo de 00_PROMPT_PARA_CODEX.txt e informe o caminho da pasta quando ela não estiver no diretório atual. O repositório deve ser o do Jumbi, não o de outro projeto mencionado no histórico.

A alternativa de arquivo único é Jumbi_APIs_e_Implementacao_Codex_v2_2026-10-14.txt, entregue separadamente. Ela reúne a especificação, o catálogo, o inventário, os critérios e as fontes. O ZIP acrescenta arquivos estruturados, ferramentas Python e testes que podem ser aproveitados no repositório.

O que cada arquivo entrega
00_PROMPT_PARA_CODEX.txt: Ordem de execução pronta para colar.
01_ESPECIFICACAO_EXECUTAVEL.md: Produto, APIs, dados, segurança, implementação e entrega.
02_CATALOGO_APIS.json: Endereços documentados, exemplos e campos não confirmados.
03_REGISTRO_TRIBUNAIS.json: Inventário documental herdado: 27 TJs e 6 TRFs, sem cobertura operacional presumida.
04_CHECKLIST_ACEITE.md: Cenários que deverão ser aprovados pela implementação futura.
05_PENDENCIAS_EXTERNAS.md: Credenciamento, representação, endpoints faltantes e dossiê institucional.
.env.integrations.example: Catálogo de variáveis, sem senhas ou tokens reais.
openapi/jumbi-integrations.openapi.json: API interna PROPOSTA: 14 caminhos e 17 operações. Não é o contrato do CNJ.
tools/: Diagnóstico público pontual, inspeção local de contratos e primitivas de segurança.
examples/pdpj_token.py: Exemplo institucional de client credentials, sem credenciais.
tests/: Testes locais dos auxiliares e da consistência deste pacote.
sources/: Fontes oficiais e limites de verificação.
reference/estudo_v1.md: Estudo anterior preservado para contexto e inventário.
VERIFICACAO_LOCAL.txt: Resultado efetivamente executado dos testes incluídos.
AGENTS.suggested.md: Regras curtas opcionais; mesclar, nunca substituir automaticamente o arquivo existente.
