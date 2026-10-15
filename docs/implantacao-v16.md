# Implantação v16 — 15/10/2026

Versão publicada em https://jumbi.nabio.pro/. Origem da revisão: commit `ba45d95` (v15). Relatório funcional: [auditoria v16](auditoria-producao-v16.md).

## Evidências

- Suíte completa no PostgreSQL do servidor: **554 testes, todos aprovados, sem pulos**, em 145,231 segundos no pacote final. Inclui os testes de concorrência que são pulados no SQLite.
- Suíte local inicial: 553 testes aprovados, 9 pulados por dependerem do PostgreSQL; o teste adicional de independência dos blocos do dashboard foi incluído na validação final do servidor.
- Testes locais finais dos módulos alterados: 50 testes aprovados.
- Navegador: 40 cenários de personalização/responsividade em 1440, 768, 390 e 320 px sem falhas. Persistência de tema, cores, densidade e menu comprovada após salvar/reabrir.
- Varredura de 68 combinações de abas/largura identificou excesso de largura em Previdenciário, Trabalhista e Triagem. Após correção, as três telas passaram nos seis cenários de 390 e 320 px, sem excesso de largura nem erros JavaScript.
- `check`, `makemigrations --check`, `pip check`, sintaxe JavaScript e `git diff --check` aprovados. Produção sem migrations pendentes.
- `collectstatic`: 190 arquivos copiados, 556 processamentos. Serviço `jumbi-v2.service` ativo; `/saude/` retorna `status: ok` por HTTPS. Login público responde HTTP 200 com cookies Secure/HttpOnly, política de cache privada, HSTS e proteção de enquadramento.
- Pós-publicação: 12 telas autenticadas responderam 200 usando sessões temporárias de teste no servidor, encerradas ao final. Login HTTPS do cliente de teste e seus estáticos passaram em 8 verificações. As cópias locais antigas das senhas de administrador e demonstração não coincidem com as atuais; as contas estão ativas e nenhuma senha foi redefinida. Isso limita a comprovação de login por senha desses dois perfis nesta rodada, mas suas telas foram verificadas por sessão de teste.
- Agendamentos de backup e lembretes ativos. Banco descartável `test_jumbi_v16_audit` removido ao concluir; banco legado preservado.

## Publicação e recuperação

- Release ativa: `/srv/jumbi/releases/20261015-v16`, acessada pelo link `/srv/jumbi/current`.
- Banco exclusivo: `jumbi_v2`.
- Backup anterior à migração: `/srv/jumbi/backups/daily/20261015T175650Z`.
- Integridade SHA-256 do dump, arquivos privados e imagens de marca conferida. Manifesto do dump lido com `pg_restore --list`; não foi realizado ensaio de restauração integral nesta rodada.
- Pacote publicado SHA-256: `34749b3b3da7770f588259d5182a54bc1822d7758c308f9a7aab9aced7ce5016`.
- Troca do link de release atômica, com reinício somente do serviço dedicado. Contas e senhas existentes preservadas.

O `check --deploy` mantém dois avisos de configuração conhecidos: HSTS sem `includeSubDomains` e sem `preload`. HTTPS e HSTS estão ativos para o domínio do JUMBI. Não se ampliou a política para outros subdomínios nem se solicitou inclusão na lista de preload nesta atualização.

Dados de credenciais anteriores foram cifrados. Uma reversão de banco exige avaliar escritas posteriores ao backup; não restaurar automaticamente. A release anterior permanece disponível, mas contém os problemas corrigidos nesta auditoria. Priorizar correção adiante e preservar dados novos.

Logs técnicos e evidências detalhadas permanecem nos diretórios privados de operação e no `tmp` local ignorado pelo Git. O repositório não inclui credenciais, cópias de banco ou documentos de clientes. Este registro documental foi acrescentado após a publicação e não integra o hash do pacote acima.
