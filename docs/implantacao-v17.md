# Implantação v17 — 15/10/2026

Publicada em https://jumbi.nabio.pro/, sobre a v16 (`cb28c18`). Escopo e limitações: [auditoria v17](auditoria-producao-v17.md).

## Evidências

- Pacote final: **568 testes aprovados no PostgreSQL, sem pulos**, em 130,478 segundos. Abrange os módulos atuais; módulos legados preservados como referência não fazem parte dessa suíte.
- `check`, `makemigrations --check`, `pip check`, sintaxe dos quatro scripts JavaScript alterados/adicionados e `git diff --check` aprovados.
- Navegador local com dados fictícios: 78 verificações de telas, responsividade, personalização, remoção de fundo, duotone, salvamento e concessão de parceria; 15 verificações finais de rolagem, controles e layouts em 1440, 768, 390 e 320 px; cinco verificações adicionais de contraste em ambos os temas, cores compostas e etapa inicial da tarefa. Rodadas finais aprovadas, sem erros JavaScript ou excesso de largura da página nos cenários medidos. Rolagem interna dos quadros permanece intencional.
- Revisão visual corrigiu títulos sem contraste e sombras excessivas dos cards no tema claro. A conferência de cores compostas usa a superfície do menu, não o elemento transparente que envolve a logo.
- Produção: 15 telas autenticadas responderam HTTP 200 em sessões temporárias, encerradas ao final; sete novos arquivos estáticos responderam HTTP 200 por HTTPS. Dez verificações adicionais confirmaram login por senha do cliente de teste, portal e seus arquivos públicos, com logout ao concluir.
- A verificação dos perfis administrador e demonstração usa sessões temporárias de teste do Django, não comprova suas senhas. Nenhuma senha foi alterada e nenhuma empresa real recebeu gratuidade automaticamente.
- Migração `billing.0004_partner_access` aplicada; nenhuma migration pendente. Valor padrão também no banco permite inserções pelos workers anteriores durante a troca de versão.
- Serviço `jumbi-v2.service` ativo, sem reinícios automáticos; `/saude/` retorna `status: ok` por HTTPS. Contagem de traceback, erro interno, timeout de worker, PermissionError e OperationalError igual a zero nas 12 horas consultadas após a publicação.
- Agendamentos de backup e lembretes ativos. Bancos descartáveis são eliminados ao encerrar os scripts de teste/restauração.

## Publicação e recuperação

- Release: `/srv/jumbi/releases/20261015-v17`, por `/srv/jumbi/current`.
- Banco exclusivo: `jumbi_v2`. Banco legado e serviços de outros sistemas preservados.
- Backup imediatamente anterior à migração: `/srv/jumbi/backups/daily/20261015T202318Z`.
- Hashes do banco, arquivos privados e imagens conferidos; manifesto do dump lido com `pg_restore --list`.
- Ensaio de restauração: o backup anterior, `20261015T175650Z`, foi restaurado com sucesso em banco temporário restrito no mesmo servidor, removido ao final. Arquivos compactados de documentos e marcas passaram por leitura integral. Não equivale a recuperação integral em um segundo servidor.
- SHA-256 do pacote publicado: `086bd19a6a113bebc65ca3de5edaa156b57f1c008453a1d07fb363fd1755be29`.
- Troca atômica do link da release; reinício somente do serviço dedicado ao JUMBI. A versão anterior permanece disponível. Restaurar banco exige avaliar escritas posteriores ao backup; não executar reversão automática que descarte dados novos.

## Pontos de atenção

Após a publicação, o disco compartilhado estava em **88% de uso, aproximadamente 12 GB livres**; swap de 2 GB quase totalmente ocupada e aproximadamente 3,4 GB de RAM disponível. Planejar capacidade antes de aumentar o volume de empresas. Não foram apagados arquivos de outros sistemas.

Permanecem os avisos conhecidos `security.W005` e `security.W021`: HSTS sem `includeSubDomains` e sem `preload`. HTTPS e HSTS estão ativos no domínio; esta publicação não amplia a política para outros subdomínios.

Integrações externas dependem de disponibilidade, habilitação e homologação específica; os testes não certificam operação de todos os tribunais nem ausência absoluta de falhas. O relatório funcional informa os limites do processamento de logos e de cada frente auditada.

Logs e evidências permanecem nos diretórios privados de operação e no `tmp` local ignorado pelo Git. Os registros finais de auditoria e implantação, a atualização do README e a inclusão dos testes de imagens na CI foram acrescentados ao repositório após a publicação e não integram o hash acima. A configuração de CI não é evidência de execução no GitHub.
