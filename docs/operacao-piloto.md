# Operação do JUMBI

## Estado da implantação — verificado em 13/10/2026

O servidor usa Ubuntu 22.04, Nginx, PostgreSQL 14 e serviços systemd. A publicação inicial ocorreu em 07/10/2026 às 20:06 UTC (17:06 em Fortaleza). A release ativa é `20261013-v6`, publicada em 13/10 às 11:46 UTC (08:46 em Fortaleza), com menu automático no desktop, navegação agrupada e layouts próprios por módulo, incluindo regras de celular e tablet. A publicação confirmou o symlink, o serviço ativo, saúde HTTPS e sucesso do backup anterior à troca. Dashboard, nichos, metas, calendário/aniversários, Kanban, contratos, rotinas, honorários, portal, segurança e contratação por WhatsApp foram preservados. Nenhuma migração, senha ou cadastro de produção foi alterado nesta atualização.

A instalação anterior do JUMBI permanece em `/var/www/apps/jumbi`, com `jumbi.service` e upstream `127.0.0.1:8040`. O banco `djumbi` é compartilhado com a instalação em `/var/www/apps/djumbi`: por esse motivo, a evolução foi feita no clone independente `jumbi_v2`. O banco original foi preservado, sem receber as migrações ou o isolamento de contas da nova versão.

| Componente novo | Configuração publicada |
| --- | --- |
| Serviço | `jumbi-v2.service`, executado pelo usuário de serviço `jumbi` |
| Upstream | `127.0.0.1:8041` |
| Release | `/srv/jumbi/releases/20261013-v6` |
| Caminho ativo da release | `/srv/jumbi/current` aponta para `/srv/jumbi/releases/20261013-v6` |
| Banco exclusivo | `jumbi_v2` |
| Configuração privada | `/srv/jumbi/shared/.env`, proprietário/grupo `root:jumbi`, modo `0640` |
| Arquivos privados | `/srv/jumbi/shared/private_media`, diretório com modo `0750` |
| Host de publicação | `jumbi.nabio.pro` |

O certificado existente de `jumbi.nabio.pro` foi conferido e é válido até **26/10/2026**. O timer de renovação do Certbot já existente está ativo. A validade atual e o timer ativo não substituem o acompanhamento da próxima renovação.

## Backup de origem e restauração

O backup anterior à evolução está em `/srv/jumbi/backups/pre-v2-20261007`, com acesso restrito a root. Ele conserva o dump do banco original, código, configuração de ambiente, configuração Nginx e unidade de serviço anteriores.

Esse dump foi restaurado em `jumbi_v2`. A comparação de fingerprints dos registros jurídicos de origem confirmou a restauração antes da evolução. As migrações e demais ajustes da release nova foram executados no clone, preservando o banco compartilhado `djumbi` e a aplicação que continua utilizando-o.

Os backups de origem e o clone permanecem **na mesma VPS**. A cópia separada fora do servidor ainda está pendente. Restaurar esse clone comprova a etapa executada; não estabelece RPO/RTO nem comprova recuperação após perda integral da VPS.

## Isolamento de contas e administração

O comando `isolate_legacy_accounts` tem simulação como padrão, exige o nome exato do banco em `--expected-db` e recusa o banco original `djumbi`. Aplicado ao clone com `--apply`, desativa contas sem vínculo ativo com escritório jurídico ativo e remove privilégios globais herdados. As contas reservadas de administração e demonstração são excluídas dessa operação. Senhas, registros e vínculos históricos são preservados.

O JUMBI mantém os modelos legados instalados para conservar as tabelas e permitir a importação. Os admins de Engenharia, Agro, Parceiros, páginas legadas e jurídico antigo foram retirados da interface. O painel e a administração de organizações/acessos exibem o escopo jurídico.

O superusuário tem painel próprio em `/plataforma/` e um escritório administrativo separado da organização de demonstração. A conta demo não possui acesso de staff ou superusuário. As credenciais geradas ficam em material local ignorado pelo Git e não devem ser incluídas em documentação, código ou relatórios públicos.

## Importação dos registros jurídicos

Após a restauração e as migrações no clone, a importação criou **9 registros** na estrutura jurídica nova:

| Registro | Quantidade |
| --- | ---: |
| Pessoas/contatos | 3 |
| Pastas jurídicas | 2 |
| Lançamentos financeiros | 2 |
| Baixas financeiras | 1 |
| Tarefas | 1 |

A repetição do comando confirmou a idempotência: os registros já importados não foram duplicados. O relatório também registra **6 pendências de conferência**. Elas precisam de revisão humana; a criação dos registros não equivale à homologação integral dos dados antigos.

O comando `import_legacy_office` é um procedimento administrativo para essa origem legada. Ele não substitui um assistente geral de importação com mapeamento de planilhas, tratamento assistido de erros e retomada pela interface. Itens antigos do tipo prazo não devem ser considerados prazos jurídicos conferidos sem revisão humana da fonte e do vencimento.

## Verificações da release

- **255 testes passaram em PostgreSQL**, em 188,298 segundos, sem testes ignorados, na v6. Os sete cenários novos cobrem filtros e sigilo dos indicadores, datas de prazos, perfis, separação de valores de clientes e estornos, paginação do pipeline e consultas financeiras constantes ao aumentar os registros.
- **256 verificações locais no navegador** passaram: 240 combinações de páginas entre 360, 390, 768, 980, 981, 1024, 1440 e 1920 px, com claro/escuro em 390/1440, mais acessos, formulários e navegação. O menu foi exercitado por mouse, teclado e toque, inclusive redimensionamento com gaveta aberta, preferência antiga e movimento reduzido. Não houve erro JavaScript ou transbordamento.
- A revisão especializada de rotinas, honorários, contratos e portal acrescentou 112 combinações de layout em sete larguras e dois temas, mais 26 verificações de filtros, navegação, prévias e tema persistente do cliente. Um ajuste final removeu texto redundante dos cabeçalhos; 28 verificações adicionais de layout, busca vazia e limpeza de filtros nas sete listas passaram após esse ajuste.
- Home, cadastro e login públicos passaram em 24 combinações nas mesmas oito larguras, sem transbordamento ou erros JavaScript.
- A v6 não exige migrações ou atualização de dependências. O backup anterior à troca terminou com sucesso. Somente `jumbi-v2.service` foi reiniciado. A primeira tentativa de saúde recebeu 502 durante a inicialização; a repetição retornou 200 e o serviço ficou ativo. Os avisos HSTS de subdomínios/preload continuam os mesmos, sem ampliar a política de outros sistemas.

- **248 testes passaram em PostgreSQL**, em 210,161 segundos, sem testes ignorados, na v5 final. A suíte inclui concorrência de publicação/aprovação/honorários, MFA e revogação de sessões, isolamento do perfil Cliente, exportação, sigilo e os fluxos anteriores. O banco temporário `test_jumbi_v2` foi removido; a verificação de 13/10 confirmou sua ausência.
- A primeira execução PostgreSQL detectou ordenação implícita removida pela agregação de parcelas e bloqueio sobre relação opcional no comando de demonstração. Ambos foram corrigidos antes de publicar. Também foram corrigidos testes dependentes da virada do intervalo TOTP e do fechamento manual de uma resposta de arquivo dentro da transação de teste. A suíte completa foi repetida e passou.
- **50 verificações locais no navegador** passaram em 390/1440 px e temas claro/escuro, sem erros JavaScript ou transbordamento. Incluem dashboard, rotinas, honorários, revisão/portal, segurança, pasta e portal externo; download privado e bloqueios de acesso do Cliente foram exercitados.
- Seis migrações aditivas foram aplicadas ao banco exclusivo, após backup com sucesso. Onze rotas autenticadas responderam 200 antes da troca da release. A primeira tentativa de saúde durante a inicialização dos workers recebeu 502; a repetição automática respondeu 200. O serviço e o backup posterior terminaram com sucesso.
- `seed_reuse_showcase` acrescentou somente exemplos fictícios à organização reservada: rotina, conferência, comentário, honorários de R$ 1.200 em três parcelas, colaborador sem senha utilizável e cliente demo com documento revisado/publicado. Repetir o comando confirmou idempotência e preservação de senhas. O seed anterior não deve ser repetido após v5: ele exige uma única associação antes de consultar seu marcador.
- As contas de superusuário e demo anteriores foram preservadas. O cliente demo não tem staff/superusuário nem acesso ao núcleo interno. A senha do cliente foi confirmada no servidor; credenciais permanecem em arquivo local ignorado, fora do pacote e do Git. MFA fica disponível para configuração pelo titular, sem cadastrar um autenticador em nome dele.

- **164 testes passaram em PostgreSQL**, em 87,757 segundos, sem testes ignorados, na versão final v4. Incluem isolamento, sigilo, planos, múltiplos nichos, metas, calendário, Kanban, contratos, exportação, concorrência e estornos financeiros. O banco temporário `test_jumbi_v2` foi removido pelo procedimento ao final.
- As seis migrações aditivas da v4 foram aplicadas no banco exclusivo. O teste de compatibilidade confirmou INSERTs da versão anterior omitindo os campos novos de organização/agenda, que possuem valores padrão no banco.
- O comando `seed_workspace_showcase` adicionou somente registros fictícios à organização reservada de demonstração: quatro nichos, pessoas/pastas, tarefas, agenda, aniversário, metas e contrato privado. É idempotente e preserva contas, senhas e registros anteriores. O telefone de exemplo é o número comercial do próprio JUMBI; nenhuma mensagem foi enviada.
- Oito rotas novas/ampliadas responderam 200 em conferência autenticada antes da troca do symlink. Após a troca, saúde HTTPS, serviço ativo e backup com `Result=success` foram confirmados.
- `check --deploy` não apontou erros; manteve dois avisos relativos a HSTS para subdomínios e preload, que continuam desativados. A publicação não ampliou a política HTTPS para outros subdomínios nem inscreveu o domínio na lista de preload.
- **106 testes passaram em PostgreSQL**, em 64,064 segundos, sem testes ignorados, na release v3. A suíte incluiu concorrência entre dois aceites de convite disputando a última vaga do plano e os redirecionamentos comerciais. O banco temporário `test_jumbi_v2` foi removido ao final.
- Verificação autenticada de **18 rotas** no ambiente de preparação concluída, incluindo acesso administrativo e de demonstração; endpoint de saúde também verificado.
- Autenticação, proteção CSRF, download privado com conferência de hash e separação entre as contas de superusuário e demonstração verificados.
- Restauração do clone e repetição da importação com idempotência comprovadas.

O relatório `docs/validacao-piloto.md` documenta a primeira entrega local e seus 55 testes; essa contagem é histórica. A matriz `docs/auditoria-documentacao.md` distingue o núcleo implementado das capacidades ainda pendentes do estudo. A liberação pública e o fluxo real de navegador foram conferidos adicionalmente conforme o registro abaixo.

## Registro de liberação ao tráfego

**Estado: publicado.**

- A v6 passou por **111 verificações no navegador de produção em 13/10/2026**, com os três logins reais, 96 combinações de páginas em 390/1440 px e temas claro/escuro, dez formulários e navegação por mouse/teclado/gaveta. Os bloqueios internos do Cliente também foram conferidos. Sem erro JavaScript ou transbordamento nas verificações concluídas. A primeira rodada parou em uma asserção imediata após redimensionamento; a automação passou a aguardar o carregamento completo e o estado da gaveta antes de interagir, e a repetição completa passou. O relatório inicial foi preservado. Não houve alteração de cadastros, senhas, envio de mensagens ou cobranças nessa checagem. A leitura operacional posterior confirmou a release v6 ativa, saúde OK, backup com sucesso e ausência do banco temporário de testes.
- A v5 passou por **65 verificações no navegador de produção em 13/10/2026**: login de superusuário, gestor demo e cliente demo; 60 combinações de páginas em 390/1440 px e temas claro/escuro; download privado e bloqueios do perfil Cliente. Não houve erros JavaScript ou transbordamento nas verificações concluídas. A medição aguarda o carregamento das folhas de estilo e fontes; uma tentativa anterior mediu o layout antes do CSS, e o relatório inicial foi preservado. A emulação de viewport não substitui teste em aparelho físico.
- A v4 passou por **35 verificações no navegador de produção**, incluindo 24 combinações de seis módulos em 390/1440 px e temas claro/escuro, com animações normais. Não houve transbordamento horizontal, erro JavaScript, falha HTTP nas verificações concluídas ou acentuação corrompida. Calendário, filtros, sino, quatro nichos da demo, metas e Kanban foram conferidos. O cadastro do superusuário ofereceu 25 nichos e permitiu selecionar quatro simultaneamente sem salvar.
- O DOCX da demonstração foi baixado e validado como Word/ZIP, com cabeçalhos privados; impressão respondeu 200, visitante anônimo foi bloqueado e a conta administrativa em outro escritório recebeu 404. Essa conferência alterou somente sessões de login, sem modificar cadastros nem enviar WhatsApp. Os fluxos de criação/movimentação haviam sido exercitados localmente e nos testes PostgreSQL.
- Um timeout de espera por `networkidle` interrompeu a primeira passagem do navegador. O relatório inicial foi preservado e somente as etapas restantes foram retomadas, aguardando DOM e componente visível. A retomada passou; a leitura autenticada de contratos foi medida em 0,101 s no Django, sem erros ou timeouts de workers no serviço. A emulação de viewport não substitui teste em aparelho físico.
- Virtual host JUMBI direcionado à porta privada 8041, com `nginx -t` aprovado e reload concluído. Os demais virtual hosts foram preservados.
- HTTPS da home retornou 200; `/saude/` retornou `{"status":"ok","application":"JUMBI"}`.
- A atualização v3 trocou o symlink da release e reiniciou somente `jumbi-v2.service`; saúde e serviço ativo foram confirmados. As rotas de contratação Start/Max responderam 302 para `wa.me/5588992745456`, com plano e preço corretos. A verificação não enviou mensagens.
- Às 20:34 UTC, a conferência da v3 no navegador de produção passou por 11 verificações: home em 390/1440 px, CSS específico de celular, pausa persistente, movimento reduzido, mensagens dos dois planos, login demo, pastas/financeiro em 360/390 px e tabela desktop. Sem erros JavaScript, respostas HTTP inesperadas ou mutações além do login. A emulação de viewport não substitui teste em aparelho físico.
- Navegador real: 13 verificações aprovadas, sem erros JavaScript nem respostas HTTP inesperadas. Foram validados login das duas contas, pessoa/pasta consultiva, prazo conferido e revisado, tarefa independente, upload/download privado, bloqueio anônimo, baixa de R$ 350 sobre R$ 1.000, saldo R$ 650, estorno para R$ 1.000 e exportação restrita à demonstração. A demo recebeu 403 ao acessar a plataforma; o administrador acessou plataforma e assinaturas.
- Somente dados fictícios foram criados para essa conferência, na organização de demonstração. Nenhum registro do escritório legado foi usado para teste destrutivo.
- O timer de backup está ativo e sua primeira execução terminou com `Result=success` e código 0.
- O backup da nova produção foi restaurado em banco temporário `jumbi_v2_restore_check`: dump e arquivos passaram no SHA-256, um arquivo privado foi confrontado com o hash armazenado, e os dados de 7 pastas/2 baixas do snapshot estavam acessíveis. O banco temporário foi removido após a validação.

Os caminhos `/media/` e `/private_media/` não devem servir arquivos jurídicos diretamente. Os documentos novos são entregues exclusivamente pelas rotas autenticadas da aplicação; o alias público da instalação anterior não deve expor a árvore privada da release nova.

## Backup operacional ativo

Os arquivos `deploy/backup-jumbi.sh`, `deploy/jumbi-backup.service` e `deploy/jumbi-backup.timer` executam o backup diário de `jumbi_v2`, arquivos privados, configuração e identificação da release. O timer define explicitamente **04:15 UTC** — **01:15 em Fortaleza** — com atraso aleatório de até cinco minutos e retenção de 14 dias na própria VPS.

**Timer ativado e primeira execução concluída.** A restauração inicial do novo conjunto foi testada. Permanecem pendentes a cópia fora da VPS e a validação periódica das próximas gerações de backup.

O pacote ZIP exportado pela aplicação serve à portabilidade dos registros e arquivos autorizados. Ele não substitui esse backup administrativo: contas, sessões e segredos não integram a exportação do escritório.

## Reversão da publicação

**V6 → V5:** esta revisão não muda o esquema nem as credenciais. A release `20261009-v5` foi preservada e mantém as barreiras de Cliente e MFA. Caso seja necessária reversão do código, preservar o backup atual, trocar atomicamente o symlink para essa v5 e reiniciar somente `jumbi-v2.service`; conferir saúde, autenticação e estáticos. Não restaurar banco por cima dos dados ativos. A advertência abaixo continua valendo para versões anteriores à v5.

**V5: não aponte simplesmente para v4/v3 após cadastrar Clientes ou ativar MFA.** Essas versões não reconhecem as novas barreiras de acesso. Prefira uma correção da v5 preservando as tabelas e dados. Se uma volta ao código antigo for inevitável, faça backup e planeje o bloqueio dos acessos externos, contas com MFA e sessões antes da troca, documentando a restauração dos acessos depois. Não remova tabelas ou restaure um dump por cima do banco ativo. As instruções v4/v3 abaixo são históricas e não autorizam contornar essas barreiras.

Para reverter apenas a v4 à v3, preservar o backup atual e trocar atomicamente `/srv/jumbi/current` para `/srv/jumbi/releases/20261007-v3`, reiniciando somente `jumbi-v2.service`. Conferir saúde, login e arquivos estáticos. As migrações aditivas e os dados novos devem permanecer no banco; o teste de compatibilidade cobre os campos novos obrigatórios. Os módulos novos ficarão inacessíveis enquanto a v3 estiver ativa, sem apagar seus registros. Essa reversão mantém o mesmo upstream 8041 e não exige mudar Nginx.

As instruções abaixo se referem a uma eventual volta à instalação legada anterior à v2, uma operação diferente e que exige reconciliação dos dados:

Antes de reverter, avaliar os registros escritos após a liberação: `jumbi_v2` e o banco original passam a divergir. A simples volta ao sistema antigo pode ocultar trabalho realizado na versão nova. Preserve o banco novo e reconcilie as alterações necessárias antes de direcionar usuários ao estado anterior.

Quando a reversão do tráfego estiver definida, restaure somente o arquivo do virtual host JUMBI conservado em `/srv/jumbi/backups/pre-v2-20261007`, voltando ao upstream anterior `127.0.0.1:8040`. Execute `nginx -t` e faça reload do Nginx apenas se a validação passar. Confira saúde e autenticação do host após a troca.

Não restaure um dump antigo sobre o banco compartilhado `djumbi`, não reverta migrações nesse banco e não apague `jumbi_v2`. O banco original também atende à outra aplicação. Conserve a release nova, seus arquivos e seus backups para reconciliação e investigação; alterações no symlink da release não substituem a reversão controlada do virtual host.

## Interface e limites conhecidos

A interface preserva a marca âmbar, temas claro/escuro, menu lateral recolhível, gaveta móvel e foco visível. O redesenho usa superfícies translúcidas e animações com pausa e preferência por movimento reduzido, com CSS e JavaScript locais. As folhas `jumbi-mobile-public.css` e `jumbi-mobile-app.css` definem composições específicas para celular: prévia pública compacta, formulários em coluna, tabelas apresentadas como cartões rotulados, fontes de formulário de 16 px e controles de pelo menos 44 px. Veja `docs/estilo-mobile.md` para as regras e evidências de viewport.

Na v4, a base visual do aplicativo usa os tokens do Nabio BJJ com a marca JUMBI. Calendário e Kanban seguem as referências do Navie Hospedagens. Em celular, o calendário usa marcadores e detalhes do dia; o Kanban dispõe de colunas empilhadas, atalhos e botão Mover, sem depender de arrastar pelo toque. A administração combina nichos em `/plataforma/escritorios/novo/`; metas e calendário estão nos dois planos, e montagem de contratos e indicadores financeiros exigem Max.

A assinatura começa por mensagem preenchida no WhatsApp comercial **+55 88 99274-5456**. O visitante decide enviar; a ativação continua administrativa após a contratação. O link comercial não implementa API de WhatsApp, cobrança automática ou confirmação de pagamento.

- Sem envio automático de convites, recuperação de senha por e-mail, armazenamento externo, antivírus de anexos, jobs, notificações garantidas ou integrações externas no núcleo atual.
- Uploads têm extensão permitida e limite de 15 MB; downloads exigem autenticação. O hash confere integridade, não ausência de conteúdo malicioso.
- Valores de clientes têm classificação separada; repasses completos, conciliação bancária e contabilidade fiscal continuam pendentes.
- Portal autenticado, revisão independente por versão/hash, publicação explícita, mensagens e revogação estão disponíveis no Max. Upload pelo cliente, assinatura eletrônica e importação geral pela interface permanecem pendentes. Downloads já publicados e revogação de acesso continuam possíveis após expiração/redução do plano, sob as mesmas permissões.
- As seis pendências da importação legada e a cópia de backup fora da VPS precisam permanecer visíveis na operação.
