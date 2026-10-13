# JUMBI · Gestão Jurídica

Evolução do código existente no servidor, orientada pelo estudo de 07/10/2026. Monólito Django 5.2 LTS com interface responsiva em português, temas claro/escuro e identidade visual enviada pelo usuário.

## Executar localmente

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edite .env e gere uma chave própria com secrets.token_urlsafe(64).
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Abra `http://127.0.0.1:8000/` e escolha o plano. O cadastro cria usuário e escritório isolado, com assinatura pendente de contratação e ativação administrativa. SQLite é exclusivo do desenvolvimento; PostgreSQL é o banco previsto para produção.

## Fluxos entregues nesta evolução

- Cadastro público, login por e-mail, troca de senha e troca de escritório por vínculo ativo.
- Convites com validade, aceitação pelo e-mail vinculado e revogação de acessos. O sistema fornece o link; não envia e-mail sem configuração de entrega.
- Pessoas, pastas consultivas ou contenciosas e processos vinculados separadamente.
- Tarefas com responsável, prioridade, vencimento e evidência de conclusão.
- Prazos manuais com origem, conferência humana, revisão motivada e cumprimento com evidência. Concluir tarefa não encerra prazo.
- Agenda, documentos privados e versões imutáveis com hash de integridade.
- Receitas, despesas e valores de clientes separados; baixas parciais e estornos com histórico. Financeiro disponível à direção/gestão no plano Max.
- Relacionamento comercial com etapas, próxima ação e motivo de perda.
- Busca e filtros nas listas, painel com números reais, auditoria e exportação ZIP com relações, arquivos autorizados e manifesto.
- Pastas sigilosas exigem acesso específico, inclusive de gestores. URLs, buscas e exportações respeitam o mesmo escopo.

Esta entrega é uma **base funcional para piloto**. Aprovação de documentos por versão e portal autenticado foram acrescentados na v5. Permanecem etapas do estudo: negociação e assinatura eletrônica de contratos, conciliação e repasses completos, filas/automações, conectores, PWA e aplicativos. Não há cálculo automático de prazo jurídico nem consulta automática a tribunais.

## Demonstração local opcional

```powershell
$env:JUMBI_DEMO_PASSWORD = 'defina-uma-senha-local-exclusiva'
.\.venv\Scripts\python.exe manage.py seed_pilot --email demo@jumbi.local
```

`seed_pilot` exige DEBUG, cria registros identificados como demonstração e nunca altera dados/senhas quando o escritório demonstrativo já existe. Para uma demonstração separada em produção, use o comando explícito `provision_accounts --with-demo-data`, com credenciais exclusivas por ambiente.

## Verificação

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test apps.discovery apps.intake apps.notifications apps.security apps.routines apps.fees apps.portal apps.legal apps.billing apps.contracts apps.performance apps.core.test_workspace apps.core.test_platform apps.core.test_legacy_isolation apps.core.test_platform_management
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

A CI executa esses testes com PostgreSQL 14. A configuração e os comandos de publicação estão em [deploy](deploy) e [operação do piloto](docs/operacao-piloto.md). A existência da configuração de CI não comprova que ela já tenha sido executada no GitHub.

## Código anterior e migração

A cópia autorizada trouxe apenas código e assets públicos de `/var/www/apps/jumbi`, sem `.env`, banco ou documentos de clientes. `apps/core` conserva identidade, organizações e suas migrations. O novo domínio vive em `apps/legal`; as rotas atuais ficam em `apps/core/workspace_urls.py` e `apps/legal/urls.py`.

Os módulos anteriores (`office`, `partners`, `engineering`, `agro`, `pages`) e a antiga configuração `config/legacy_urls.py` foram preservados como referência/migração, mas suas rotas não são publicadas na configuração atual. Seus testes antigos refletem outra experiência e não compõem a suíte do piloto. O comando `import_legacy_office` oferece simulação e importação idempotente dos registros legados, preservando os originais. Datas de pagamentos desconhecidas permanecem desconhecidas. A execução em produção é registrada no relatório de implantação.

Veja [auditoria do estudo](docs/auditoria-documentacao.md) para o escopo real e suas pendências. A publicação utiliza banco exclusivo, serviço dedicado e backup privado; evidências operacionais constam do registro de implantação.

## Planos

Start: R$ 299,90/mês, 5 usuários ativos, 300 pastas ativas e 1.000 versões de documentos, incluindo CRM e mapa de clientes. Max: R$ 599,90/mês, 20 usuários ativos, 2.000 pastas ativas e 5.000 versões, incluindo financeiro, honorários, contratos, portal, estoque e patrimônio. Ambos incluem calendário, Kanban, metas operacionais, auditoria e exportação dos dados autorizados. Ativação e vigência são administradas em `/admin/billing/organizationsubscription/`; não há cobrança automática ou gateway.

A contratação pode começar pelo WhatsApp: os botões dos planos preenchem a mensagem com plano e valor para o número comercial informado. A mensagem depende do envio pelo visitante; abrir o link não ativa assinatura.

As regras próprias da experiência em celular ficam em [estilo mobile](docs/estilo-mobile.md), com folhas de estilo distintas para a página pública e o aplicativo.

## Evolução de 09/10/2026

Dashboard operacional com indicadores, nichos combinados, metas, calendário e aniversariantes. A administração cria escritórios e escolhe múltiplas áreas em `/plataforma/escritorios/novo/`. Nichos filtram pastas, indicadores, calendário e Kanban. Metas e calendário integram Start e Max; indicadores financeiros e montagem de contratos exigem Max.

A agenda usa calendário mensal e categorias separadas para prazos, tarefas, compromissos e datas importantes; aniversariantes de clientes autorizados abrem mensagem preenchida no WhatsApp para envio manual. O Kanban preserva evidência ao concluir e motivo ao reabrir. A montagem de contratos gera DOCX privado e versões preservadas, com impressão/salvar PDF.

Referências funcionais lidas no servidor: calendário/Kanban do Navie Hospedagens e montagem de contratos do Autos. Estilização do aplicativo adaptada dos tokens do Nabio BJJ, com a marca dourada JUMBI e regras específicas de celular. Consulte [nichos e metas](docs/nichos-e-metas.md), [contratos](docs/montagem-contratos.md) e [operação](docs/operacao-piloto.md).

## Reaproveitamentos da auditoria — v5

Rotinas por nicho com cinco exemplos editáveis, prévia, aplicação única à pasta, tarefas no Kanban, checklist de documentos e comentários internos. Honorários Max com parcelamento exato, recorrência mensal finita e integração às baixas e estornos. Documentos Max com revisão independente vinculada à versão e ao hash, publicação explícita para cada cliente, revogação e mensagens. A conta Cliente acessa somente os arquivos publicados para ela; consulta interna e Cliente são perfis diferentes.

Segurança de conta inclui TOTP opcional, códigos de recuperação de uso único e revogação de outras sessões em ambos os planos. O financeiro não efetua cobranças externas; a aprovação documental não equivale a assinatura eletrônica. Os limites de usuários ativos incluem os vínculos Cliente. A exportação inclui os novos registros autorizados e preserva portabilidade após expiração ou redução do plano; arquivos já publicados continuam disponíveis ao destinatário enquanto o vínculo e a publicação estiverem ativos.

Consulte [rotinas](docs/routines.md), [honorários](docs/honorarios.md), [portal](docs/portal.md) e [segurança](docs/seguranca-conta.md). Os 117 itens do levantamento representam referências e alternativas; esta versão implementa as primeiras quatro frentes, não a totalidade do catálogo.

## Experiência por módulo — v6

Menu automático por mouse no desktop, com expansão por teclado, gaveta móvel e controle manual em telas grandes de toque. Navegação agrupada por rotina, acervo, comercial e administração. Pastas, pessoas, processos, prazos, documentos, financeiro e relacionamento têm apresentações próprias, com filtros, ações existentes e indicadores sobre o escopo autorizado. As demais abas receberam composição e orientação específicas. Os formulários explicam como cada registro participa do fluxo do escritório.

As regras de celular, tablet e desktop e a pesquisa nas páginas oficiais de Astrea, ADVBOX, Projuris e Legal One estão em [experiência e concorrentes](docs/experiencia-e-concorrentes.md). O documento separa decisões desta revisão das integrações e funcionalidades propostas para etapas futuras.

## Organização e importação — v7

Busca unificada em sete áreas com até 12 filtros pessoais salvos; central persistente de avisos internos, leitura e arquivamento; importação assistida CSV/XLSX de pessoas e processos, com prévia, duplicidades e confirmação atômica; agenda em mês, semana e dia com sobreposições de responsável e composição própria no celular. Disponíveis nos dois planos, conforme os papéis de acesso. Importação é exclusiva de direção e gestão.

O timer `jumbi-reminders.timer` gera os avisos e limpa prévias expiradas a cada 15 minutos. Não envia mensagens externas, não captura tribunais e não calcula prazos automaticamente. Veja [organização e importação](docs/organizacao-e-importacao.md) para regras, limites e operação.

## Fichas, colaboração e recursos do escritório · v8

- Fichas PF/PJ com endereço, dados profissionais/cadastrais, representantes, situação e observações; pastas e vínculos autorizados na página da pessoa.
- Página individual de documento com versões, hashes, revisões e publicações existentes, sem publicação automática.
- Comentários imutáveis por tarefa, acessíveis pelo Kanban, com autor/data e proteção contra duplicidade.
- Exportação ZIP por pasta, com registros vinculados, originais e manifesto de integridade. A exportação do escritório também inclui comentários, estoque e patrimônio conforme as permissões.
- Estoque e patrimônio no Max para direção/gestão: materiais, categorias, fornecedores, lotes, validade, entradas, consumo, perdas, contagem, estornos e compras com recebimento confirmado. Equipamentos têm responsável/local/situação e histórico. Nenhum pagamento é lançado automaticamente.
- Django Admin jurídico limitado ao escritório e às pastas autorizadas; ser superusuário não concede acesso ao conteúdo de terceiros.
- Mapa nacional por UF com filtros e ranking, baseado nos cadastros autorizados, sem envio de dados a serviços externos. Arquivos geográficos locais com atribuição ao IBGE.
- Pessoas e Processos com indicadores clicáveis, filtros, ordenação e paginação; profissões/faixas etárias e distribuição por nicho calculadas sobre os registros existentes. Agenda por responsável/situação, recortes do Kanban e CRM em quadro ou lista.
- Guia “Como usar o JUMBI”, explicações recolhíveis e layouts específicos para celular. Start inclui CRM, mapa e a operação jurídica; Max acrescenta a gestão financeira e os recursos avançados publicados.

Consulte [a matriz da documentação v0.2](docs/requisitos-v02.md) e [os fluxos de estoque e patrimônio](docs/estoque-e-patrimonio.md). A matriz distingue recursos entregues de etapas futuras, como editor rico, assinatura e integrações judiciais. A arquitetura permanece Django SSR/PostgreSQL.

Veja também [planos e limites](docs/planos-e-assinatura.md), [mapa de clientes](docs/mapa-clientes.md) e [aprimoramentos das referências de interface](docs/referencia-interface.md).
