# Organização do escritório — v7

## Busca unificada

`/busca/` reúne pessoas, pastas, processos, documentos, tarefas, prazos e compromissos. Busca de 2 a 120 caracteres e até oito palavras, combinadas nos campos dos cadastros. Não pesquisa o conteúdo dos arquivos, dados financeiros ou registros de outros escritórios. O filtro de nicho usa as áreas configuradas para a organização.

Cada resultado é consultado com as mesmas permissões e regras de sigilo do módulo de origem. Perfis de consulta recebem links de leitura. O perfil Cliente permanece restrito ao portal. Até 12 buscas pessoais podem ser salvas por usuário e escritório; são critérios, não cópias dos resultados. Revogações e mudanças de acesso valem na próxima consulta. Salvar e excluir exigem POST com CSRF.

## Central de notificações

`/notificacoes/` mantém avisos pessoais de tarefas e prazos vencidos ou com vencimento nos próximos três dias, além de aniversários de clientes vinculados a pastas acessíveis no dia do aniversário. Os registros visíveis ao membro podem incluir obrigações de outros responsáveis da equipe.

Leitura, não leitura, arquivamento e restauração persistem entre acessos. Ler ou arquivar não conclui tarefa nem cumpre prazo. Obrigações concluídas continuam consultáveis na caixa, mas deixam o contador de pendências. Uma alteração de vencimento gera uma ocorrência nova e oculta a ocorrência da data anterior. Títulos, links, aniversários e sigilo são reavaliados a partir do cadastro atual.

A central atualiza ao ser aberta e pelo serviço `jumbi-reminders.timer`, a cada 15 minutos. A geração é idempotente por destinatário, registro e data da ocorrência. Não é um serviço de entrega externa garantida: e-mail, push e envio automático de WhatsApp não são implementados. A mensagem de aniversário no WhatsApp só fica disponível no próprio dia na central, mediante telefone válido; o usuário revisa e envia. A regra de 29/02 em anos não bissextos permanece 28/02, como no calendário.

## Importação assistida

`/importar/` permite à direção e à gestão importar **Pessoas** e **Processos em pastas já existentes**, nos planos Start e Max. Não cria pastas, usuários, documentos ou lançamentos financeiros. Não aumenta os limites contratados. As mesmas restrições de assinatura e sigilo são verificadas no envio, na prévia e na confirmação.

1. Baixe o modelo Excel ou CSV e preencha os cabeçalhos reconhecidos. O CSV precisa estar em UTF-8. A tela permite consultar IDs de pastas autorizadas.
2. Envie até 2 MB, 500 linhas de dados e 12 colunas, com uma única aba preenchida. Fórmulas, macros, vínculos externos e arquivos com expansão excessiva são rejeitados. Documento, telefone e número de processo devem ser texto no Excel, preservando dígitos e zeros iniciais.
3. Confira a associação de cabeçalhos e os dados de cada linha. Possíveis duplicidades e campos inválidos bloqueiam o lote inteiro. Corrija a planilha e envie de novo; não há sobrescrita nem importação parcial silenciosa.
4. Marque a conferência e confirme. O sistema revalida o lote e as permissões dentro da transação. Repetir a confirmação não duplica os registros. Cada inclusão entra na auditoria e a tela apresenta o comprovante.

Os arquivos originais não ficam armazenados. Os valores da prévia ficam no banco privado, vinculados ao usuário e escritório, por até 24 horas; o comando `purge_import_previews` remove prévias expiradas. É possível descartar uma prévia manualmente. Depois de importar, o payload é apagado e fica um comprovante com tipo, data e contagem. Possíveis homônimos podem ser conferidos e cadastrados individualmente pela tela Pessoas.

## Agenda diária e semanal

`/juridico/calendario/` oferece Mês, Semana e Dia, salto por data, categorias e nichos. A semana começa na segunda-feira. Compromissos usam horários de Fortaleza; prazos jurídicos e entregas de tarefas ficam em faixa separada, sem horário presumido. O término do compromisso é exclusivo: terminar à meia-noite não ocupa o dia seguinte.

Na grade desktop, compromissos simultâneos ocupam colunas distintas. O aviso de sobreposição considera somente compromissos visíveis do mesmo responsável, sem alterar datas ou calcular prazos legais. No celular, a semana usa dias expansíveis com listas próprias; o dashboard mantém o calendário mensal compacto. Aniversariantes acompanham o período mostrado.

## Operação

As migrations de `discovery`, `notifications` e `intake` são aditivas. O timer usa o usuário `jumbi`, o ambiente privado da aplicação e não grava em arquivos de clientes. Um mesmo ciclo executa `generate_notifications` e `purge_import_previews`. Verifique `systemctl status jumbi-reminders.timer` e `systemctl show jumbi-reminders.service -p Result -p ExecMainStatus`; logs contêm contagens, não payloads.

Para voltar ao código v6, desative primeiro o timer novo e preserve as tabelas/dados v7, sem reverter migrations nem restaurar dump sobre o banco ativo. O v6 conserva as barreiras de Cliente e MFA; os recursos v7 ficam indisponíveis até sua reativação. A programação de backup existente permanece separada.
