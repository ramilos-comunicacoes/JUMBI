# Auditoria e personalização — v16

Data: 15/10/2026. Base examinada: v15, commit ba45d95. Esta auditoria cobre o código publicado do JUMBI, testes dos módulos ativos e verificações operacionais do serviço dedicado. Não constitui certificação de segurança nem homologação de serviços externos.

## Correções de produção

- Pesquisa DJEN passa a consultar a fonte configurada. Exemplos não são mais inseridos automaticamente. Falha, coleta parcial e limite de páginas ficam explícitos. Recoletar preserva a revisão humana.
- Conectores sem implementação homologada deixam de anunciar validação, sincronização ou prática de atos oficiais bem-sucedidas. Credenciais armazenadas são cifradas, inclusive as existentes. Webhook exige segredo exclusivo e verifica assinatura e repetição.
- Triagem exige pasta autorizada, vencimento informado e justificativa da conferência. Revisar novamente não duplica tarefas ou prazos. O sistema não calcula prazo jurídico a partir da data da consulta.
- Prazo de exigência INSS usa data cadastrada; sem data, aparece “a conferir”. Indeferimento deixa de ser classificado como deferimento.
- Mensagens, rotina, redistribuição, recibos, relatórios e linha do tempo passam a respeitar o acesso às pastas sigilosas. Dados financeiros continuam limitados a gestores habilitados no Max.
- API interna exige perfil de gestão, valida dados e registra chaves de idempotência. Credenciais não aparecem nas respostas.
- Tarefas canceladas deixam de entrar como pendências ou atrasos. A administração abre corretamente para superusuário sem escritório selecionado.
- Upload de marca é decodificado, limitado e normalizado em PNG, inclusive no administrador. Extensão ou MIME isolados não são suficientes. SVG não é aceito como upload.
- Backup diário passa a incluir também as imagens de marca, além de banco, arquivos privados e configuração protegida.

## Personalização disponível

Em **Personalização & Visual**, direção/gestão pode configurar por escritório:

- Nome, contatos, título, logo, favicon e ícone do menu recolhido.
- Cores da marca, fundo do menu, contraste automático do texto e intensidade de vidro.
- Tema padrão, espaçamento no desktop, texto ampliado e redução de movimento.
- Menu automático ou manual, ordem das abas e abas opcionais ocultas.
- Nichos combinados, página inicial, dashboard completo ou resumido e blocos independentes.
- Calendário inicial em mês, semana ou dia, mensagem de aniversário e nome padrão para pesquisa no DJEN.

Há prévia da marca, explicações por campo, seções recolhíveis no celular e proteção contra edição concorrente. Tema escolhido no dispositivo tem chave por pessoa e escritório. O portal do cliente usa a identidade do escritório. Esconder menu nunca altera permissões; trocar aparência nunca libera funções fora do plano. Alertas essenciais de prazo permanecem visíveis.

## Limitações explícitas

- DJEN é pesquisa manual, com orçamento de páginas e dependência da disponibilidade/resposta do serviço oficial. Não promete cobertura integral nem substitui conferência na origem.
- PDPJ/Domicílio, MNI, eproc, INSS/PREVJUD e assinatura eletrônica dependem de implementação/homologação e autorizações específicas. O catálogo deixa essa condição visível; não simula sucesso.
- Calculadoras jurídicas preliminares, sem regras e validação suficientes, foram retiradas dos módulos especializados; os cadastros e acompanhamentos permanecem.
- Dados anteriores de DJEN têm origem não verificada identificada por migration, sem apagar registros nem alterar prazos já revisados.
- Criptografia usa chave derivada da SECRET_KEY. Sua rotação requer recifrar credenciais com a chave anterior disponível; não basta substituir a variável.
- Os planos continuam Start R$ 299,90 e Max R$ 599,90, com contratação por WhatsApp e ativação administrativa; não há cobrança automática.

## Verificação e publicação

Os testes incluem isolamento entre escritórios e pastas, permissões, planos, documentos, operações financeiras, estoque, concorrência, personalização e falhas dos conectores. `config.test_settings` reduz apenas o custo de hash de senha em testes; a configuração de produção mantém o hasher seguro padrão.

A publicação exige: teste PostgreSQL em banco descartável, `check`, migrations sem divergências, `pip check`, coleta de estáticos, backup verificado, migrations no banco exclusivo `jumbi_v2`, troca atômica da versão e verificação HTTPS. O banco legado não é usado. Restaurar backup exige janela controlada e avaliação de escritas posteriores; não restaurar automaticamente sobre dados novos.

As evidências finais da execução ficam no registro de implantação da v16. Testes aprovados não garantem ausência absoluta de defeitos nem homologam integrações externas.
