# Planos e assinatura

O catálogo mensal confirmado para o JUMBI é **Start por R$ 299,90/mês** e **Max por R$ 599,90/mês**. Os preços, rótulos e limites vêm de `apps/billing/plans.py`; formulários, assinatura e mensagens de contratação utilizam esse catálogo.

## Capacidades

| Capacidade por escritório | Start | Max |
| --- | ---: | ---: |
| Preço mensal | R$ 299,90 | R$ 599,90 |
| Usuários ativos | 5 | 20 |
| Pastas jurídicas ativas | 300 | 2.000 |
| Versões de documentos | 1.000 | 5.000 |

Os limites são finitos. Não há promessa de usuários, arquivos ou pastas ilimitados.

- **Usuários:** contam vínculos ativos de pessoas com conta ativa, incluindo contas de clientes do portal. Aceitar novamente um convite para quem já está ativo não consome outra vaga. Convites pendentes ainda não ocupam uma vaga; a disponibilidade é conferida ao aceitar.
- **Pastas:** contam pastas em andamento ou aguardando. Pastas encerradas permanecem no histórico e deixam de consumir capacidade ativa. Reabrir uma pasta exige vaga disponível. Uma pasta pode reunir mais de um processo: o limite é de pastas ativas, não de números de processos.
- **Documentos:** cada versão preservada consome uma unidade, inclusive versões anteriores do mesmo documento. O limite individual de arquivo continua em 15 MB. O sistema não apaga versões antigas para abrir capacidade.

## Funcionalidades por plano

| Funcionalidade | Start | Max |
| --- | --- | --- |
| Painel jurídico, nichos combinados, pessoas PF/PJ e pastas | Incluído | Incluído |
| Processos, prazos e conferência de cumprimento | Incluído | Incluído |
| Calendário mensal, semanal e diário; aniversários | Incluído | Incluído |
| Tarefas Kanban, histórico e comentários | Incluído | Incluído |
| Documentos privados, versões e fichas de documentos | Incluído | Incluído |
| Rotinas por nicho e metas operacionais | Incluído | Incluído |
| Relacionamento com clientes e oportunidades (CRM) | Incluído | Incluído |
| Busca unificada, filtros salvos e notificações internas | Incluído | Incluído |
| Importação assistida de pessoas e processos | Incluído | Incluído |
| Mapa de clientes, conforme endereços e localização cadastrados | Incluído | Incluído |
| Equipe, auditoria, segurança da conta e exportação autorizada | Incluído | Incluído |
| Financeiro, baixas, estornos e metas de receita | — | Incluído |
| Honorários e cronogramas de parcelas | — | Incluído |
| Modelos e montagem de contratos | — | Incluído |
| Solicitar revisão documental e publicar no portal do cliente | — | Incluído |
| Estoque, lotes, compras e patrimônio do escritório | — | Incluído |

O plano libera recursos; o perfil e as permissões continuam delimitando quem pode utilizá-los. Por exemplo, financeiro, honorários e estoque são restritos à direção e gestão, mesmo no Max. Consulta não pode criar oportunidades no CRM; clientes acessam somente seu portal e sua conta. Pastas sigilosas continuam exigindo acesso explícito.

O CRM no Start permite cadastrar pessoas relacionadas, oportunidades, etapas, responsáveis e próximas ações. Valores estimados em oportunidades não registram receitas, despesas ou pagamentos.

## Contratação e ativação

Os botões de contratação abrem o WhatsApp comercial com uma mensagem contendo plano, preço vigente e capacidade. A mensagem é preparada; o usuário decide enviá-la. Parâmetros externos de preço ou telefone não alteram o catálogo nem o destinatário configurado.

O cadastro público cria uma assinatura **aguardando contratação**. Solicitar outro plano registra o interesse e mantém plano e situação atuais até a análise administrativa. A administração ativa o acesso após a contratação. Não há cobrança automática, processamento de cartão, débito ou pagamento registrado por clicar em contratar, enviar mensagem ou solicitar mudança.

Esta atualização muda o catálogo de preço e capacidade. Ela **não altera o status das assinaturas existentes**, não gera cobrança retroativa, não registra pagamento e não confirma renegociação contratual. A migração dos rótulos das opções de plano preserva os códigos `start` e `max` e os demais dados das assinaturas.

## Expiração, redução de plano e preservação de dados

Assinaturas pendentes, suspensas ou expiradas não recebem acesso operacional normal. Antes de reduzir um plano, o sistema verifica se usuários ativos, pastas ativas e versões de documentos cabem no plano escolhido; não remove registros automaticamente.

A exportação autorizada dos registros e arquivos continua disponível após expiração ou redução do plano, respeitando o perfil, o escritório ativo e o sigilo das pastas. Documentos já publicados continuam acessíveis ao cliente autorizado, desde que o vínculo, a publicação e as permissões permaneçam válidos. Novas revisões, publicações e mensagens de gestão seguem os controles do Max.

## Validação

Os testes de assinatura cobrem limites, concorrência por vagas no PostgreSQL, criação e reabertura de pastas, preservação das versões, migração para plano menor, preços enviados ao WhatsApp, solicitação sem ativação automática e acesso ao CRM no Start. Também conferem que Start não libera financeiro, honorários, contratos, estoque ou novas revisões/publicações do portal.
