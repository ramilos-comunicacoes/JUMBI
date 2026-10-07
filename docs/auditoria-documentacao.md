# Auditoria do JUMBI em relação ao estudo de produto

Referência: `Estudo_Comparativo_Sistemas_Juridicos_2026-10-07.pdf`, especialmente seções 8 a 13, páginas 9 a 18. Revisão do código em 07/10/2026.

**O estudo não está integralmente implementado.** Existe um núcleo funcional de gestão jurídica com persistência, permissões, financeiro básico e exportação. As quatro fases propostas no estudo incluem capacidades adicionais que continuam pendentes. Publicar o núcleo ou redesenhar sua interface não conclui essas fases.

Esta auditoria confronta os requisitos propostos com as rotas efetivamente ligadas em `config/urls.py`, os modelos e serviços de `apps/core`, `apps/legal` e os testes do produto. Código legado em `apps/office`, `apps/partners`, `apps/engineering` ou `apps/agro` não é contado como funcionalidade jurídica entregue quando suas rotas não fazem parte desta aplicação. O estudo é uma direção de produto, não evidência de que os recursos dos concorrentes já existam no JUMBI.

## Matriz de implementação

| Tema do estudo | Situação | Evidência e alcance real |
| --- | --- | --- |
| Identidade, escritório e equipe | Implementado no núcleo | Cadastro, login por e-mail, alteração de senha, convites expirantes e revogáveis, perfis proprietário/gestor/operador/consulta. `apps/core/workspace_views.py`, `workspace_forms.py`, `workspace_auth.py` e `test_workspace.py`. Envio automático do convite e recuperação de senha por e-mail continuam pendentes. |
| Isolamento e pastas sigilosas | Implementado na aplicação | Organização obtida da associação ativa; consultas, formulários, downloads e exportação filtrados. Pasta sigilosa exige responsável ou participante autorizado, mesmo para gestor. `workspace_middleware.py`, `legal/models.py::TenantModel`, `legal/services.py::visible_matters`, testes de domínio e de views. PostgreSQL RLS e testes de isolamento com papel de banco restrito não estão implementados. |
| Pessoas, partes e representantes | Parcial | Pessoas físicas/jurídicas com contato e documento; cliente da pasta e contraparte textual no processo. Ainda não existem `MatterParty`, `CourtCaseParty`, representantes estruturados, múltiplos papéis ou campos configuráveis. |
| Pastas e processos | Implementado no núcleo, estrutura avançada parcial | Pasta consultiva sem processo ou com vários processos; natureza, área, situação, responsável, cliente e sigilo. Processo registra número, órgão, contraparte e notas. Não existe linha de eventos processuais externos ou estrutura completa de partes por processo. |
| Tarefas e capacidade | Parcial | Responsável, prioridade, data, estado, evidência de conclusão e histórico; tarefa concluída não encerra prazo. Faltam estimativas, dependências, catálogo de trabalho, revisão, férias e substituição coordenada de todas as responsabilidades. |
| Controladoria e prazos | Parcial | Prazo manual com origem, responsável, conferência humana, revisão com motivo e data anterior, nova conferência e cumprimento com evidência textual. Não há fila `SourceEvent`, cálculo de dias úteis/feriados/suspensões, deduplicação de publicações ou comprovante obrigatório estruturado de protocolo. |
| Agenda | Implementado no núcleo | Compromissos com início/fim, local, responsável e pasta opcional. Não existem sincronização externa, recorrência ou notificações com estado de entrega. |
| Arquivos e versões privadas | Implementado no núcleo | Documento lógico, versões preservadas, autor, nome original, hash SHA-256, classificação e download autorizado. Validação de extensão e tamanho; arquivos privados sem URL pública. Faltam aprovação por versão, publicação ao cliente, comparação de conteúdo, retenção configurável e inspeção antimalware. |
| Modelos, cláusulas e contratos | Pendente | Não há gerador documental determinístico, biblioteca versionada de cláusulas, entrevista, snapshot dos dados de geração ou ciclo de negociação/aprovação/assinatura/renovação. Anexar um contrato não implementa esse fluxo. |
| CRM e contratação | Parcial | Oportunidade com contato, etapa, responsável, valor, próxima ação e motivo de perda obrigatório. Faltam origem/área/interesse estruturados, verificação assistida de conflitos, proposta, aceite, contrato e conversão rastreável da oportunidade em trabalho contratado. |
| Financeiro do escritório | Parcial | Lançamentos de receita/despesa/valores de cliente, valores decimais, vencimento, baixa parcial, estorno preservado e saldo. A chave de operação impede duplicar uma baixa repetida. Não há contas bancárias, centros de custo, categorias, competência, parcelamento, recorrência, cobrança automática ou conciliação bancária. |
| Recursos de clientes e repasses | Parcial | Classificação separa recursos de cliente da receita do escritório. Ainda não existem titularidade, destinação, autorização, comprovantes e reconciliação completa do exemplo de R$ 10.000 → R$ 2.000 + R$ 500 + R$ 7.500. |
| Portal do cliente | Pendente | Não existem conta externa delimitada por conteúdo, solicitações, publicação explícita, leitura pelo cliente ou envio de documentos pelo portal. O perfil de consulta é um perfil interno de equipe; não equivale a esse portal. |
| Comentários e colaboração | Pendente | O núcleo jurídico não possui comentários, menções ou solicitações contextualizadas. Convite de equipe não implementa acesso temporário de parceiro por pasta nem chat. |
| Indicadores e busca | Parcial | Painel com pastas, tarefas, prazos e receitas abertas; listas pesquisáveis e filtros vinculados às permissões. Não há BI de carteira, margem, capacidade, retrabalho ou tempo de ciclo com todas as definições e períodos previstos. |
| Auditoria | Implementado no núcleo, governança avançada parcial | Eventos de alterações, prazos, arquivos, pagamentos e exportação com ator/organização/data/objeto. Histórico jurídico não pode ser editado pelos fluxos comuns ou pelo admin jurídico. Não há armazenamento externo inviolável, política completa de retenção ou acesso temporário de suporte com motivo e expiração. |
| Exportação | Implementado para o núcleo entregue | ZIP com `records.json`, manifesto, contagens, identificadores, relações, usuários com nome de exibição e arquivos com SHA-256. Respeita sigilo e perfil financeiro. Testes leem o pacote e conferem relações e hashes. Não é backup de usuários/sessões/segredos nem importador de retorno. |
| Importação e migração | Parcial — comando legado validado | `import_legacy_office` converte cadastros do JUMBI anterior com simulação padrão, aplicação explícita, transação, relatório de pendências e proveniência idempotente. Preserva sigilo, origem e saldos; prazos exigem conferência e pagamentos antigos mantêm data/operador desconhecidos. Documentos legados ou inconsistências interrompem a operação. Testes cobrem repetição, isolamento, rollback, exportação e conversão. Falta assistente de importação para o usuário com mapeamento de arquivos externos. |
| Administração do SaaS | Parcial | Painel exclusivo de superusuário, contagem de organizações/usuários, consulta de acessos e Django admin. Escritório pessoal administrativo e demonstração separados. Administração global de dados jurídicos é somente consulta; operações de domínio continuam na aplicação. Faltam gestão completa de suporte, consentimento para suporte, consumo e faturamento automático. |
| Assinaturas e planos | Parcial, contratação manual | `apps/billing` separa a assinatura SaaS dos lançamentos financeiros do escritório: Start R$ 89,90/mês e Max R$ 199,90/mês, estados pendente/ativa/demo/suspensa, validade, limites por plano, solicitação de mudança, ativação administrativa e histórico. Max libera financeiro e CRM; redução de plano valida capacidade. Exportação mantém acesso por perfil após vencimento/suspensão da assinatura. Não há checkout, pagamento confirmado por provedor, renovação/cancelamento automático ou emissão fiscal. Os preços foram definidos pelo responsável nesta revisão, não inferidos da pesquisa de concorrentes. |
| Jobs e automações | Pendente | Não há Celery/RabbitMQ, outbox transacional, `AutomationRun`, simulação, pausa, tentativas ou retomada de workflows. A idempotência de pagamentos não comprova idempotência de jobs ausentes. |
| Integrações, captura e IA | Pendente | Sem conector processual, DataJud, DJEN, assinatura eletrônica, API de WhatsApp, calendário externo, OCR ou IA. Há link comercial para abrir uma mensagem de contratação no WhatsApp, sem envio automático nem sincronização. O núcleo opera sem essas APIs. Nenhuma cobertura jurídica externa é prometida. |
| API e aplicativos | Parcial | Backend Django com templates e JavaScript local, interface web responsiva. Não há API DRF pública, frontend React/TypeScript, PWA instalável, empacotamento Capacitor/Tauri ou sincronização offline. React era uma recomendação de arquitetura do estudo, não obrigação para o núcleo funcionar. |
| Backup, recuperação e operação | Parcial, restauração inicial validada | Publicação HTTPS, banco exclusivo, backup diário e restauração isolada com conferência de hashes executados; evidências em `docs/operacao-piloto.md`. Faltam cópia fora da VPS, restaurações periódicas e definição/teste de RPO/RTO. Não se afirma disponibilidade garantida. |

## Critérios das fases do estudo

| Fase | Conclusão desta auditoria | O que impede considerá-la integralmente concluída |
| --- | --- | --- |
| 0 — Fundação verificável | Parcial | Isolamento, autenticação, convites, sigilo e arquivos existem; restauração inicial documentada. Ainda faltam tarefa assíncrona com organização/idempotência, cópia de backup fora da VPS e rotina de recuperação validada periodicamente. |
| 1 — Operação piloto | Parcial, núcleo utilizável | Fluxo pessoa → pasta → tarefa → prazo → arquivo disponível; importação legada por comando com simulação e retomada idempotente. Faltam comentários, assistente de importação para o usuário, partes estruturadas e substituição coordenada de responsáveis. |
| 2 — Gestão e relacionamento | Parcial | CRM básico, financeiro com baixas/estornos e exportação disponíveis. Faltam contratação, repasses completos, modelos reproduzíveis, aprovação/publicação, portal e regras simuláveis. |
| 3 — Expansão validada | Pendente | Conectores, automações avançadas, calendário jurídico, aplicativos e IA ainda não foram implementados e validados. |

## Evidências automatizadas

- `apps/core/test_workspace.py`: cadastro isolado, login, revogação, suspensão, convites, perfis e seleção do escritório.
- `apps/legal/tests/test_domain.py`: vínculos entre organizações, sigilo, prazo/tarefa independentes, conferência/revisão, recebimento parcial/estorno, idempotência, valores de cliente e versões privadas.
- `apps/legal/tests/test_views.py`: autenticação, autorização por objeto, proteção CSRF, sigilo em listagens/painel/auditoria/formulários, atomicidade de upload e exportação com relações e hashes.
- `apps/core/test_platform.py`: acesso exclusivo do superusuário, login sem vínculo, provisionamento idempotente, senhas pelo ambiente, isolamento da demonstração e admin jurídico somente consulta.

Nesta revisão, os 12 testes de `apps.core.test_platform` foram executados localmente com sucesso, incluindo provisionamento com `DEBUG=False` e enforcement de assinatura habilitado. O teste usa banco isolado e arquivos fictícios; não substitui a verificação das credenciais e das rotas no servidor publicado.

A revisão de isolamento acrescentou 10 testes em `apps.core.test_legacy_isolation`. A execução conjunta dos 22 testes de plataforma/isolamento passou: simulação sem mutações, recusa do banco original, preservação de senhas e vínculos, desativação de acessos herdados, ocultação do admin legado e quotas ao ativar vínculos ou usuários pelo admin. O comando `isolate_legacy_accounts` exige `--expected-db`, funciona em simulação por padrão e só altera contas com `--apply`; ele se recusa a executar no banco original `djumbi`. O isolamento foi aplicado exclusivamente ao clone `jumbi_v2`, conforme o registro operacional.

O relatório anterior `docs/validacao-piloto.md` registra 55 testes da primeira entrega e verificações no navegador. Essa contagem é histórica: a revisão atual acrescenta testes. O resultado final da suíte e os testes em produção devem constar do registro de implantação; uma função de teste no código, sozinha, não comprova sua execução na release publicada.

## Condições comerciais implementadas nesta revisão

| Plano | Preço mensal | Usuários ativos | Pastas ativas | Versões de documentos | Financeiro e CRM |
| --- | ---: | ---: | ---: | ---: | --- |
| Start | R$ 89,90 | 3 | 100 | 200 | Não incluídos |
| Max | R$ 199,90 | 15 | 1.000 | 2.000 | Incluídos |

Auditoria e exportação dos registros autorizados estão disponíveis nos dois planos. A cota documental conta versões preservadas, não apenas documentos lógicos. O cadastro registra solicitação; a ativação e alterações são feitas pelo superusuário, com histórico. Solicitação, vigência ou ativação não constituem comprovante de pagamento. O escritório administrativo recebe Max ativo e a conta de testes recebe Max em demonstração, em organizações separadas. Senhas não são registradas neste documento ou no código.

## Próximas entregas com maior impacto

1. Criar assistente de importação de arquivos externos para o usuário e substituição coordenada de responsáveis. A conversão do legado JUMBI já dispõe de comando idempotente com simulação e relatório de pendências.
2. Entregar comentários, solicitação de documentos e portal com compartilhamento explícito por versão.
3. Construir contratação, modelos documentais reproduzíveis e aprovação de documentos.
4. Completar repasses e conciliação, mantendo recursos de clientes separados da receita própria.
5. Introduzir processamento assíncrono com outbox e idempotência antes de integrações e notificações.
6. Validar desempenho com PostgreSQL, restauração periódica e procedimentos de suporte antes de ampliar escala e conectores.

## Validação da publicação

A release v3 passou por **106 testes em PostgreSQL**, incluindo concorrência real da última vaga de usuário e redirecionamento para contratação pelo WhatsApp. Na publicação inicial, 13 verificações no domínio HTTPS confirmaram os dois logins, permissões, persistência, fluxo de prazo/tarefa, arquivo privado, recebimento parcial/estorno e exportação restrita à demonstração. O primeiro backup da nova produção foi restaurado e seus arquivos conferidos por SHA-256. Veja [operação](operacao-piloto.md). Esses resultados validam o núcleo entregue; não transformam itens pendentes desta matriz em funcionalidades concluídas.
