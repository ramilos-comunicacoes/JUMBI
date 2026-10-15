# Implantação v18 — quadro de tarefas do Navie

Adaptação direta do quadro existente no Navie Hospedagens, sobre a v17
(`0acb63e`). A origem do código, a licença e as regras de negócio preservadas
estão em [quadro-navie.md](quadro-navie.md).

## Entrega

- Quatro colunas: Atrasadas, A fazer, Em andamento e Finalizadas. As seis etapas
  reais continuam identificadas nos cards, nos filtros e no histórico.
- Cards com prioridade, responsável, pasta vinculada, entrega e detalhes;
  criação e edição em janela sem sair do quadro.
- Arraste por mouse e toque, com confirmação da etapa. Alternativa Mover
  acessível por teclado, com motivo/evidência nas transições de finalização.
- Quatro colunas no desktop; rolagem lateral, atalhos de coluna e controles de
  toque no celular. Listas internas rolam sem alargar a página.
- Filtros compartilhados entre quadro e lista. Cada coluna apresenta até 100
  cards, informa o total real e permite abrir a lista completa com paginação.
- Estado do servidor e contadores recarregados após cada salvamento. Arrastar
  não modifica datas; a posição interna permanece ordenada por vencimento.

## Validação

- Suíte completa dos módulos atuais: **575 testes aprovados no PostgreSQL,
  sem pulos**, em 109,342 segundos, no banco descartável
  `test_jumbi_v18_audit`. O banco de produção não foi usado para os testes.
- `check`, `makemigrations --check --dry-run` e `pip check` aprovados.
- 41 verificações de navegador com registros fictícios: claro/escuro em 1440,
  768, 390 e 320 px; filtros, detalhes, seis etapas, motivos, contadores,
  concorrência de movimentação, consulta sem edição, cadastro/edição,
  validações, IDs de campos, rótulos e retorno de foco.
- Arraste por toque exercitado com eventos CDP do Chromium. É uma simulação
  de toque; não equivale a uma homologação em todos os aparelhos físicos.
- Sem erros JavaScript ou excesso de largura global nas telas verificadas.
  A rolagem lateral interna do quadro é intencional.
- Sintaxe JavaScript e `git diff --check` aprovados. Nenhuma migration nova.

## Produção e recuperação

- Publicada em [JUMBI](https://jumbi.nabio.pro/juridico/quadro/), release
  `/srv/jumbi/releases/20261015-v18`, pelo link `/srv/jumbi/current`.
- 17 telas autenticadas responderam HTTP 200, incluindo quadro, lista e
  cadastro de tarefas; as quatro colunas e o editor foram conferidos no HTML
  da produção. Dez assets responderam HTTP 200 por HTTPS, incluindo Sortable,
  JavaScript e CSS do quadro.
- Dez verificações adicionais de HTTPS confirmaram login por senha do cliente
  de teste e portal. Para administrador/demonstração, a checagem das telas usa
  sessões temporárias do Django e não valida suas senhas. Todas essas sessões
  foram encerradas; nenhuma credencial foi alterada.
- `jumbi-v2.service` ativo, zero reinícios automáticos e `/saude/` com
  `status: ok`. Zero ocorrências de traceback, erro interno, timeout de worker,
  PermissionError e OperationalError nas 12 horas de logs consultadas.
- Backup anterior à ativação:
  `/srv/jumbi/backups/daily/20261015T205521Z`. Hashes do banco, arquivos privados
  e imagens conferidos; manifesto do dump lido com `pg_restore --list`.
- Sem migrations pendentes. Banco descartável de teste removido. Os testes não
  gravaram tarefas nas empresas de produção; os cenários de edição e arraste
  usam registros fictícios locais e o banco isolado.
- Troca atômica da release e reinício somente do serviço JUMBI. A v17 permanece
  disponível para reversão de código; não é necessária alteração de esquema
  nesta entrega. Restaurar banco exige considerar escritas posteriores.
- SHA-256 do pacote publicado:
  `d39d3e8c3cfc404e6ce0566d2e6e4df4d8079adac920a1c9277e188d70d8465d`.

Backup e lembretes continuam agendados. O servidor compartilhado apresenta
88% de uso do disco (cerca de 12 GB livres) e swap quase ocupada; a capacidade
continua sendo um ponto operacional a acompanhar, conforme a auditoria v17.
Permanecem os avisos conhecidos HSTS `security.W005` e `security.W021`, sem
`includeSubDomains`/`preload`; HTTPS e HSTS do domínio permanecem ativos.

Relatórios detalhados e capturas estão no `tmp` local ignorado pelo Git; logs
operacionais estão no diretório privado de implantação do servidor. Este
relatório final e a entrada v18 do README foram adicionados ao repositório
depois de gerar o pacote e não integram o hash acima. A configuração de CI
não é evidência de execução no GitHub.
