# Rotinas por nicho

Modelos do escritório combinam múltiplas áreas de atuação, tarefas, conferências e documentos a solicitar. Direção e gestão criam, personalizam e arquivam modelos. Operadores aplicam modelos e colaboram nas pastas autorizadas; consulta e cliente não alteram os registros.

## Comportamento

- A página do modelo apresenta uma prévia. O usuário escolhe uma pasta e uma data operacional para as tarefas, revisa e confirma.
- A aplicação cria tarefas reais no Kanban, atribuídas à pessoa que aplica, e itens de checklist. Não cria prazos jurídicos nem calcula dias úteis. Os arquivos são enviados separadamente em Documentos.
- Uma rotina é aplicada no máximo uma vez por pasta. Bloqueio de linha e restrição única impedem duplicação por repetição do envio. A versão exibida deve corresponder à versão corrente do modelo.
- A aplicação guarda um retrato imutável do modelo; edições posteriores não mudam o trabalho aplicado. Itens concluídos requerem evidência; reabertura requer motivo e verifica a versão concorrente. O histórico conserva ambos.
- Comentários são internos, texto simples escapado, imutáveis, sem envio de mensagem a terceiros. Autores históricos permanecem após revogação de acesso.
- Os exemplos de catálogo são sugestões operacionais editáveis; documentos e ações são revisados pela equipe conforme cada caso.
- Recursos disponíveis no Start e Max com assinatura ativa. A exportação pode usar o escopo de leitura mesmo após encerramento da assinatura.

## Integração

1. Adicionar `apps.routines` a `INSTALLED_APPS`; incluir `apps.routines.urls` em `/rotinas/` com namespace `routines`.
2. Navegação `routines:list` e ícone `routines`.
3. Na pasta, atualizar contexto com `matter_context(user, organization, matter)` e incluir `routines/matter_panel.html`. Carregar `css/jumbi-routines.css`.
4. Dashboard opcional: `dashboard_routines(user, organization)` retorna contagem e quatro pendências em pastas visíveis.
5. Exportar `RoutineTemplate`, `RoutineApplication`, `MatterChecklist`, `MatterComment`. Aplicações/checks/comments via `visible_records`; templates do próprio tenant (inclusive arquivados para portabilidade). Auditoria de operações de pasta é vinculada à própria pasta; eventos de template devem entrar em `accessible_audit`.
6. `manage.py migrate`; testes `manage.py test apps.routines`.

## Preservação de acesso

Todos os serviços de escrita verificam assinatura, papel ativo e acesso explícito às pastas sigilosas. O superusuário não ganha acesso às pastas sem vínculo e autorização. Consultas de detalhes e identificadores de formulário ficam restritas ao escritório ativo. Nenhum dado de cliente é copiado dos projetos de referência.
