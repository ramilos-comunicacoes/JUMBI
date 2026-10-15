# Auditoria operacional e melhorias — v17

Data: 15/10/2026. Base: v16, commit cb28c18. O JUMBI Gov foi retirado do escopo a pedido do usuário; nenhum sistema da procuradoria foi localizado ou alterado.

## Acesso de parceiros

Em **Administração JUMBI → empresa → Plano e acesso**, o superusuário pode conceder **Parceiro — gratuito e ilimitado**, suspender o acesso ou voltar a um plano comercial. A mesma opção está na criação de escritórios e no administrador de assinaturas.

Essa condição libera os recursos do Max, custa R$ 0,00, não vence e elimina os limites comerciais de usuários, pastas e versões de documentos. Os valores públicos continuam Start R$ 299,90 e Max R$ 599,90. Permissões individuais, sigilo de pastas, isolamento de empresas, limites técnicos de arquivos e disponibilidade de integrações são mantidos.

Somente o superusuário pode conceder a condição. Alterações ficam registradas no histórico da assinatura e na auditoria. Edições concorrentes são recusadas. Retirar a condição exige que o uso caiba no plano escolhido; nenhum registro é apagado. A suspensão bloqueia a operação de parceiros também. Não foram concedidas parcerias a empresas reais nesta publicação.

## Logos sem fundo e contraste

O upload identifica e remove fundos uniformes conectados às bordas, preserva transparência existente e converte o resultado em PNG. A prévia usa o mesmo processamento do salvamento e não grava arquivos. Limites: entrada de até 2 MB e 20 milhões de pixels; saída de até 1.024 px no maior lado, sem metadados.

Imagens ambíguas, fotografias, fundos complexos ou sem desenho distinguível recebem uma explicação para enviar PNG transparente ou fundo uniforme. O sistema não promete recorte semântico de qualquer fotografia. Partes internas fechadas da marca são preservadas para evitar apagar detalhes.

No menu expandido/recolhido, na prévia e no portal, o navegador mede o contraste sobre a superfície real. Se parte relevante do desenho não tiver contraste suficiente, gera uma apresentação duotone com cores contrastantes. A apresentação se atualiza ao trocar cores ou tema, preservando o arquivo original tratado. O favicon recebe transparência; não se presume a cor da interface externa do navegador.

## Interface baseada no Navie Hospedagens

Referência lida no servidor: `/var/www/apps/navievibe/hoteis/templates/hoteis/base_partner.html`, `partner_dashboard.html` e `atividades/partials/kanban.html`. Foram adaptados os padrões de cabeçalhos, espaçamento, cards, foco dos campos, seta e contraste dos selects e rolagem interna de quadros/tabelas.

O JUMBI usa seus próprios tokens por escritório e controles nativos. O Kanban no celular passa a deslizar por colunas, com botões de rolagem e indicação textual; tabelas largas mantêm o excesso de largura dentro da região. Há regras próprias de espaçamento, tamanho de campos e áreas de toque no celular. Preferência de movimento reduzido permanece respeitada.

## Falha encontrada nesta auditoria

A central de integrações validava perfil e empresa, mas não conferia assinatura ativa. A interface e a API agora recusam empresas com assinatura suspensa ou vencida. Operações da API repetem a conferência após obter o bloqueio do escritório para impedir gravações com autorização desatualizada.

O botão de adicionar tarefa por coluna enviava a etapa na URL, mas o cadastro a ignorava. A etapa inicial agora é exibida no formulário e aplicada com histórico. Concluir e cancelar continuam sendo ações posteriores; a coluna de canceladas também recebeu descrição correta.

## Operação e limites da verificação

A inspeção inicial encontrou serviço ativo, sem reinícios automáticos, saúde HTTPS normal e nenhum traceback, erro HTTP 500, timeout de worker ou erro de banco/permissão registrado nas 12 horas consultadas. Migrations aplicadas, dependências consistentes e agendamentos de backup/lembretes ativos.

Além de conferir hashes, o backup anterior foi restaurado com sucesso em banco temporário restrito no próprio servidor, removido ao final. Os arquivos de documentos e marca passaram por leitura integral de seus arquivos compactados. Isso não equivale a ensaio completo de recuperação em outro servidor.

Na inspeção inicial, o disco compartilhado do servidor estava em 87% de uso, com aproximadamente 13 GB livres; a swap estava ocupada. A medição após a publicação consta do registro de implantação. Não foram removidos dados ou releases de outros sistemas. Planejar capacidade e investigar crescimento antes de ampliar o volume de escritórios.

DJEN continua dependente da fonte oficial e de conferência humana. PDPJ/Domicílio, MNI, eproc, INSS/PREVJUD e assinatura eletrônica não devem ser anunciados como homologados. A auditoria não certifica ausência absoluta de falhas.

Resultados finais dos testes e publicação: `implantacao-v17.md`.
