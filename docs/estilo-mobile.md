# Estilo móvel do JUMBI

## Composição própria do aplicativo jurídico

O aplicativo usa `static/css/jumbi-mobile-app.css`, carregado por `templates/legal/base.html` somente até 720 px, depois do CSS comum e dos estilos específicos da página. O celular tem uma composição própria: cabeçalho compacto, navegação por gaveta, leitura em uma coluna, controles para toque e registros apresentados como cartões. O conteúdo não é reduzido com `transform: scale()` para caber na tela.

### Contrato de layout

- Margens de 16 px, respeitando `safe-area-inset-*`; viewport com `viewport-fit=cover`.
- Cabeçalho de aproximadamente 64 px com menu, tema, acesso à conta e saída. O título completo permanece no conteúdo, evitando duplicação no cabeçalho.
- Botões, links de ação e controles de cabeçalho com área mínima de 44 px; itens da gaveta têm pelo menos 48 px.
- Inputs, selects e textareas com fonte de 16 px e altura mínima de 48 px. Labels de 14 px e formulários em uma coluna.
- Indicadores do painel em grade 2 × 2; demais seções operacionais seguem uma coluna. Nenhuma informação ou ação essencial é retirada para economizar espaço.
- Ações de registro distribuídas em botões que podem ocupar múltiplas linhas. Campos longos podem quebrar texto; valores monetários preservam os centavos.
- Navegação da pasta usa um índice de seções com botões, sem depender de uma faixa horizontal de abas.
- Tema claro e escuro usam os mesmos tokens. A preferência `prefers-reduced-motion` desativa animações e transições.

### Tabelas no celular

Tabelas de listas, financeiro, painel, pasta, equipe, auditoria e administração usam a classe `mobile-records`. Cada célula recebe `data-label` com o nome de sua coluna; listas dinâmicas usam o filtro `column_at` de `apps/legal/templatetags/legal_ui.py`. Cada linha se apresenta como um cartão rotulado. Não há colunas essenciais ocultas nem obrigação de arrastar uma tabela larga para encontrar ações.

Os elementos de tabela conservam papéis explícitos de acessibilidade (`table`, `rowgroup`, `row`, `columnheader` e `cell`). O cabeçalho é recortado apenas visualmente no celular; não usa `display:none` ou `visibility:hidden`. A gaveta mantém foco controlado, fecha com Escape e devolve o foco ao botão do menu.

No desktop, as tabelas continuam tabelas. As únicas correções comuns desta revisão são o espaço entre o ícone e o texto de busca e a preservação visual dos valores monetários.

### Páginas e manutenção

O CSS cobre painel, listas e filtros, formulários, detalhes de pasta, documentos/versionamento, equipe, auditoria, assinatura e painel administrativo. A assinatura usa `jumbi-billing.css` para seu cartão; o arquivo móvel sobrescreve somente sua composição para celular. Links, formulários de contratação e WhatsApp mantêm o comportamento existente.

Ao criar uma tabela nova, incluir os rótulos de todas as células e a semântica de tabela antes de aplicar `mobile-records`. Ao criar um controle, conferir alvo de toque e leitura com a fonte padrão do dispositivo. Não utilizar `overflow-x:hidden` no corpo como correção de conteúdo que excede a tela.

## Verificação desta revisão

QA em Chrome headless local, com dados fictícios e preferência de movimento reduzido:

- 8 rotas em 360 e 390 px: painel, pastas, financeiro, formulário de pessoa, detalhe de pasta, equipe, auditoria e assinatura.
- Respostas HTTP 200 verificadas antes das capturas; largura do documento igual à viewport, sem overflow horizontal.
- Controles de ação com pelo menos 44 px; inputs presentes com fonte de 16 px; cartões com todos os campos rotulados e cabeçalhos acessíveis.
- Gaveta com fechamento por Escape e retorno de foco; amostra do tema claro e inspeção visual de cartões, painel e formulários.
- Amostra desktop em 1440 px mantém `display: table` e `table-header-group`; sem erro JavaScript no fluxo verificado.

Evidências temporárias: `tmp/qa-mobile-app-results.json` e capturas `tmp/qa-mobile-app-*.png`. São artefatos locais de QA, ignorados pelo Git. A verificação usa emulação de viewport: não substitui testes físicos em iOS/Android nem afirma conformidade integral de acessibilidade.

## Página inicial e acesso público

`static/css/jumbi-mobile-public.css` é carregado somente até 720 px, depois dos estilos compartilhados. A composição pública móvel usa título e chamada curtos, informação de preço antes da ação, botão principal largo e uma prévia compacta de recursos própria. O painel ilustrativo inclinado do desktop não é reduzido para caber no telefone.

As regras móveis definem áreas de toque de pelo menos 44 px, campos de 16 px, margens próprias, safe areas e planos em coluna única. Preços, limites e ativação após contratação continuam visíveis. Partículas e luzes ocupam uma área menor para preservar a leitura. Pausa de efeitos e preferência por movimento reduzido se aplicam também ao celular.

A verificação pública cobriu 360, 390, 520, 720 e 1440 px nos temas claro/escuro, sem overflow ou erros JavaScript; troca entre prévia móvel/desktop, formulários e URLs dos dois planos foram conferidos.

## Conferência após publicação

Em 07/10/2026 às 20:34 UTC, a release v3 publicada em `https://jumbi.nabio.pro` passou por 11 verificações de navegador. Home em 390/1440 px e pastas/financeiro em 360/390 px mantiveram a largura do documento igual à viewport. Campos de busca tinham fonte de 16 px; controles, pelo menos 44 px; cartões conservaram todos os rótulos. A tabela desktop permaneceu tabela. Pausa persistente e preferência por movimento reduzido interromperam as animações contínuas. Nenhum erro JavaScript ou resposta HTTP inesperada foi registrado. Relatório local ignorado pelo Git: `tmp/qa-production-v3-results.json`.

## Ampliação de 09/10/2026

A base autenticada usa `jumbi-workspace.css`, adaptada dos tokens do Nabio BJJ: superfícies neutras, borda de 1 px, raios de 8/12/16/24 px, topo de 64 px e cor de destaque dourada JUMBI. A classe exclusiva `j-office-shell` evita conflitos com as ilustrações animadas da página pública.

Dashboard, calendário, Kanban, metas e contratos possuem composições específicas até 720 px. No calendário, células compactas mostram pontos por categoria e os detalhes aparecem abaixo; no Kanban, as colunas se empilham e possuem atalhos, com ação Mover disponível para toque/teclado. A entrevista de contrato e a prévia ficam em sequência; a impressão tem CSS próprio. Nenhum documento A4 é reduzido para caber na tela. A conferência local cobriu telas de 360/390/1440 px e temas claro/escuro, incluindo movimento normal.
