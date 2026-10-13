# Auditoria do JUMBI em relação ao estudo de produto

Referência: `Estudo_Comparativo_Sistemas_Juridicos_2026-10-07.pdf`, especialmente seções 8 a 13, páginas 9 a 18. Revisão do código em 09/10/2026.

**O estudo não está integralmente implementado.** Existe um núcleo funcional de gestão jurídica com persistência, permissões, financeiro básico e exportação. As quatro fases propostas no estudo incluem capacidades adicionais que continuam pendentes. Publicar o núcleo ou redesenhar sua interface não conclui essas fases.

Esta auditoria confronta os requisitos propostos com as rotas efetivamente ligadas em `config/urls.py`, os modelos e serviços de `apps/core`, `apps/legal` e os testes do produto. Código legado em `apps/office`, `apps/partners`, `apps/engineering` ou `apps/agro` não é contado como funcionalidade jurídica entregue quando suas rotas não fazem parte desta aplicação. O estudo é uma direção de produto, não evidência de que os recursos dos concorrentes já existam no JUMBI.

## Matriz de implementação

| Tema do estudo | Situação | Evidência e alcance real |
| --- | --- | --- |
| Identidade, escritório e equipe | Implementado no núcleo | Cadastro, login por e-mail, alteração de senha, convites expirantes e revogáveis, perfis proprietário/gestor/operador/consulta e Cliente externo. TOTP opcional, recuperação de uso único e revogação de outras sessões em apps/security. `apps/core/workspace_views.py`, `workspace_forms.py`, `workspace_auth.py` e `test_workspace.py`. Envio automático do convite e recuperação de senha por e-mail continuam pendentes. |
| Isolamento e pastas sigilosas | Implementado na aplicação | Organização obtida da associação ativa; consultas, formulários, downloads e exportação filtrados. Pasta sigilosa exige responsável ou participante autorizado, mesmo para gestor. `workspace_middleware.py`, `legal/models.py::TenantModel`, `legal/services.py::visible_matters`, testes de domínio e de views. PostgreSQL RLS e testes de isolamento com papel de banco restrito não estão implementados. |
| Pessoas, partes e representantes | Parcial | Pessoas físicas/jurídicas com contato e documento; cliente da pasta e contraparte textual no processo. Ainda não existem `MatterParty`, `CourtCaseParty`, representantes estruturados, múltiplos papéis ou campos configuráveis. |
| Pastas e processos | Implementado no núcleo, estrutura avançada parcial | Pasta consultiva sem processo ou com vários processos; natureza, área, situação, responsável, cliente e sigilo. Processo registra número, órgão, contraparte e notas. Não existe linha de eventos processuais externos ou estrutura completa de partes por processo. |
| Tarefas e capacidade | Parcial | Quadro Kanban com atraso automático, movimentação persistida, verificação de estado concorrente, evidência de conclusão, motivo de reabertura, data real e histórico; tarefa concluída não encerra prazo. Catálogo de rotinas por nicho, prévia, aplicação idempotente, checklist e comentários entregues. Faltam estimativas, dependências, revisão coordenada das tarefas, férias e substituição coordenada de todas as responsabilidades. |
| Controladoria e prazos | Parcial | Prazo manual com origem, responsável, conferência humana, revisão com motivo e data anterior, nova conferência e cumprimento com evidência textual. Não há fila `SourceEvent`, cálculo de dias úteis/feriados/suspensões, deduplicação de publicações ou comprovante obrigatório estruturado de protocolo. |
| Agenda | Implementado no núcleo, calendário ampliado | Calendário mensal e agenda com categorias separadas de prazos, tarefas, compromissos e datas importantes; navegação por mês/dia/nicho; eventos multidiários. Notificação interna de aniversários de clientes autorizados, com mensagem personalizada de WhatsApp para envio manual. Sem sincronização externa, recorrência ou entrega automática. |
| Arquivos e versões privadas | Implementado no núcleo | Documento lógico, versões preservadas, autor, nome original, hash SHA-256, classificação e download autorizado. Validação de extensão e tamanho; arquivos privados sem URL pública. Revisão independente por versão/hash, decisão imutável, publicação explícita e revogação entregues no Max. Faltam comparação de conteúdo, retenção configurável e inspeção antimalware. |
| Modelos, cláusulas e contratos | Parcial — montagem entregue | Biblioteca de modelos editáveis com variáveis literais, preenchimento cadastral, entrevista, prévia, DOCX privado, impressão/PDF pelo navegador e versões imutáveis com snapshot e hashes. Plano Max. Faltam biblioteca independente de cláusulas versionadas, negociação, assinatura eletrônica e renovação. As versões documentais podem passar pela revisão independente do portal. Veja `docs/montagem-contratos.md`. |
| CRM e contratação | Parcial | Oportunidade com contato, etapa, responsável, valor, próxima ação e motivo de perda obrigatório. Faltam origem/área/interesse estruturados, verificação assistida de conflitos, proposta, aceite, contrato e conversão rastreável da oportunidade em trabalho contratado. |
| Financeiro do escritório | Parcial | Lançamentos de receita/despesa/valores de cliente, valores decimais, vencimento, baixa parcial, estorno preservado e saldo. A chave de operação impede duplicar uma baixa repetida. Honorários parcelados e programação mensal finita de 1–36 meses integram o financeiro, com prévia, centavos exatos e criação idempotente. Não há contas bancárias, centros de custo, categorias, competência, cobrança externa automática ou conciliação bancária. |
| Recursos de clientes e repasses | Parcial | Classificação separa recursos de cliente da receita do escritório. Ainda não existem titularidade, destinação, autorização, comprovantes e reconciliação completa do exemplo de R$ 10.000 → R$ 2.000 + R$ 500 + R$ 7.500. |
| Portal do cliente | Implementado no núcleo; solicitações avançadas pendentes | Perfil Cliente externo, vínculo explícito com contato, publicações individuais de versões aprovadas, download privado com integridade, mensagens e revogação. Acesso já publicado persiste após vencimento/redução do plano enquanto vínculo/publicação estiverem ativos; novas publicações e mensagens exigem Max. Faltam upload pelo cliente, solicitações estruturadas e notificações externas. Consulta permanece perfil interno distinto. |
| Comentários e colaboração | Parcial — comentários entregues | Comentários internos imutáveis por pasta e conversa contextualizada por publicação no portal, com autoria e histórico. Faltam menções, solicitações estruturadas, acesso temporário de parceiro e notificações garantidas. |
| Indicadores e busca | Parcial — dashboard ampliado | Indicadores autorizados de pastas/processos/clientes/tarefas/prazos/documentos/financeiro, série de novas pastas, distribuição por nicho, metas com progresso manual ou calculado, calendário e aniversários. Superusuário configura múltiplos nichos por escritório; filtros permitem visão mesclada ou por área. Faltam margem, capacidade, retrabalho e todas as definições avançadas de BI do estudo. |
| Auditoria | Implementado no núcleo, governança avançada parcial | Eventos de alterações, prazos, arquivos, pagamentos e exportação com ator/organização/data/objeto. Histórico jurídico não pode ser editado pelos fluxos comuns ou pelo admin jurídico. Não há armazenamento externo inviolável, política completa de retenção ou acesso temporário de suporte com motivo e expiração. |
| Exportação | Implementado para o núcleo entregue | ZIP com `records.json`, manifesto, contagens, identificadores, relações, usuários com nome de exibição e arquivos com SHA-256. Respeita sigilo e perfil financeiro. Testes leem o pacote e conferem relações e hashes. Não é backup de usuários/sessões/segredos nem importador de retorno. |
| Importação e migração | Parcial — comando legado validado | `import_legacy_office` converte cadastros do JUMBI anterior com simulação padrão, aplicação explícita, transação, relatório de pendências e proveniência idempotente. Preserva sigilo, origem e saldos; prazos exigem conferência e pagamentos antigos mantêm data/operador desconhecidos. Documentos legados ou inconsistências interrompem a operação. Testes cobrem repetição, isolamento, rollback, exportação e conversão. Falta assistente de importação para o usuário com mapeamento de arquivos externos. |
| Administração do SaaS | Parcial — criação de contas ampliada | Painel de superusuário com criação atômica de escritório, responsável sem privilégios globais, plano/estado de assinatura e múltiplos nichos. Edição de áreas exclusiva do superusuário. Escritório administrativo e demonstração separados; controles por perfil e auditoria. Faltam suporte completo com consentimento e faturamento automático. |
| Assinaturas e planos | Parcial, contratação manual | `apps/billing` separa a assinatura SaaS dos lançamentos financeiros do escritório: Start R$ 89,90/mês e Max R$ 199,90/mês, estados pendente/ativa/demo/suspensa, validade, limites por plano, solicitação de mudança, ativação administrativa e histórico. Max libera financeiro e CRM; redução de plano valida capacidade. Exportação mantém acesso por perfil após vencimento/suspensão da assinatura. Não há checkout, pagamento confirmado por provedor, renovação/cancelamento automático ou emissão fiscal. Os preços foram definidos pelo responsável nesta revisão, não inferidos da pesquisa de concorrentes. |
| Jobs e automações | Pendente | Não há Celery/RabbitMQ, outbox transacional, `AutomationRun`, simulação, pausa, tentativas ou retomada de workflows. A idempotência de pagamentos não comprova idempotência de jobs ausentes. |
| Integrações, captura e IA | Pendente | Sem conector processual, DataJud, DJEN, assinatura eletrônica, API de WhatsApp, calendário externo, OCR ou IA. Há link comercial para abrir uma mensagem de contratação no WhatsApp, sem envio automático nem sincronização. O núcleo opera sem essas APIs. Nenhuma cobertura jurídica externa é prometida. |
| API e aplicativos | Parcial | Backend Django com templates e JavaScript local, interface web responsiva. Não há API DRF pública, frontend React/TypeScript, PWA instalável, empacotamento Capacitor/Tauri ou sincronização offline. React era uma recomendação de arquitetura do estudo, não obrigação para o núcleo funcionar. |
| Backup, recuperação e operação | Parcial, restauração inicial validada | Publicação HTTPS, banco exclusivo, backup diário e restauração isolada com conferência de hashes executados; evidências em `docs/operacao-piloto.md`. Faltam cópia fora da VPS, restaurações periódicas e definição/teste de RPO/RTO. Não se afirma disponibilidade garantida. |

## Critérios das fases do estudo

| Fase | Conclusão desta auditoria | O que impede considerá-la integralmente concluída |
| --- | --- | --- |
| 0 — Fundação verificável | Parcial | Isolamento, autenticação, convites, sigilo e arquivos existem; restauração inicial documentada. Ainda faltam tarefa assíncrona com organização/idempotência, cópia de backup fora da VPS e rotina de recuperação validada periodicamente. |
| 1 — Operação piloto | Parcial, núcleo utilizável | Fluxo pessoa → pasta → tarefa → prazo → arquivo disponível; importação legada por comando com simulação e retomada idempotente. Faltam assistente de importação para o usuário, partes estruturadas e substituição coordenada de responsáveis. |
| 2 — Gestão e relacionamento | Parcial | CRM básico, financeiro com baixas/estornos e exportação disponíveis. Montagem determinística com modelos e versões entregue. Aprovação/publicação por versão, portal e programação de honorários entregues. Faltam contratação completa, repasses e regras automatizadas simuláveis. |
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
2. Ampliar o portal já entregue com solicitações estruturadas, uploads pelo cliente e notificações externas.
3. Completar negociação, aprovação, assinatura e renovação; a montagem documental determinística e as versões já foram entregues.
4. Completar repasses e conciliação, mantendo recursos de clientes separados da receita própria.
5. Introduzir processamento assíncrono com outbox e idempotência antes de integrações e notificações.
6. Validar desempenho com PostgreSQL, restauração periódica e procedimentos de suporte antes de ampliar escala e conectores.

## Validação da publicação

A release v3 passou por **106 testes em PostgreSQL**, incluindo concorrência real da última vaga de usuário e redirecionamento para contratação pelo WhatsApp. Na publicação inicial, 13 verificações no domínio HTTPS confirmaram os dois logins, permissões, persistência, fluxo de prazo/tarefa, arquivo privado, recebimento parcial/estorno e exportação restrita à demonstração. O primeiro backup da nova produção foi restaurado e seus arquivos conferidos por SHA-256. Veja [operação](operacao-piloto.md). Esses resultados validam o núcleo entregue; não transformam itens pendentes desta matriz em funcionalidades concluídas.

## Ampliação de 09/10/2026

Dashboard, nichos múltiplos, metas, calendário/aniversários, Kanban e montagem de contratos foram implementados e publicados na release `20261009-v4`. As referências de UX foram consultadas no código do servidor: Navie Hospedagens, Nabio BJJ e Autos. Controles de acesso, exportação e histórico foram estendidos aos novos registros. A versão final passou por 164 testes em PostgreSQL; implantação, migrações, demonstração e backups constam do registro operacional. A existência desses módulos não conclui as etapas ainda pendentes acima.
