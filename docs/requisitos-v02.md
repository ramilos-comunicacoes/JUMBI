# Requisitos v0.2 — aproveitamento na release v8

O documento funcional recebido em 13/10/2026 descreve a visão de produto completa. Esta entrega aproveita os requisitos compatíveis com a base em funcionamento, acrescenta inventário e estoque e preserva os dados existentes. A matriz abaixo distingue funcionalidades implementadas de objetivos futuros; a especificação inteira não está concluída. Os resultados de testes e da publicação ficam no registro operacional da release.

## Novas funcionalidades

| Requisito | Implementação v8 | Limites explícitos |
| --- | --- | --- |
| Ficha PF/PJ (§4) | Nome/razão social, CPF/CNPJ, contatos, nascimento, profissão, nome fantasia, inscrições, endereço, representantes, observações internas e status do relacionamento. Página individual com pastas autorizadas, vínculos do portal e histórico. | Campos complementares opcionais. Representantes são informações cadastrais; não validam identidade nem concedem acesso. Status inativo não revoga acesso nem encerra pastas. Campos personalizados e cadastro estruturado de múltiplos representantes ficam para evolução. |
| Mapa nacional de clientes (solicitação complementar) | Distribuição nas 27 UFs a partir do estado/país cadastrados. Filtros de tipo, nome/cidade e cadastros com pasta acessível; lista paginada por estado e atalhos para as fichas. Disponível para a equipe nos dois planos. | Representa cadastros, não processos, coordenadas ou endereço exato. Um cliente conta uma vez. País estrangeiro, estado ausente e estado não reconhecido aparecem separados. Não há inferência por CEP nem envio dos dados de clientes a serviços de mapas. |
| Documento individual (§6.2) | Página própria com contexto da pasta/cliente, autoria, datas, versões preservadas, SHA-256, downloads privados, revisões e publicações autorizadas. Atalhos para revisão da versão e criação de tarefa/prazo na pasta. | Tarefa e prazo dos atalhos são vinculados à pasta; não existe vínculo documental específico. Hash não comprova assinatura. Não há editor rico, preview de todos os formatos nem solicitação de assinatura. |
| Conversa de tarefas (§9.4) | Página da tarefa com comentários cronológicos, autor, horário e histórico preservado, sob o mesmo acesso da tarefa e da pasta. | Menções, anexos de comentário, indicadores individuais de leitura e notificações por comentário não estão implementados. |
| Exportação por pasta (§16.1) | ZIP específico da pasta com os registros relacionados autorizados, versões de documentos, metadados e manifesto de integridade. Reutiliza as verificações da exportação geral. | Geração síncrona. Exportação de todas as pastas de um cliente em uma operação e processamento volumoso em segundo plano com link expirável ficam para evolução. |
| Inventário e estoque (solicitação complementar) | Módulo próprio inspirado nas rotinas de Navie Hospedagens: catálogo, fornecedores, compras, lotes, movimentos, consumo, ajustes/estornos e bens patrimoniais. Histórico e isolamento por escritório. | O módulo organiza materiais e patrimônio do escritório. Não substitui o cadastro de bens de inventário sucessório, obrigações fiscais, compras bancárias ou emissão de notas. Consulte a documentação operacional de estoque para papéis e regras de cada operação. |
| Sigilo administrativo (§18) | O Django Admin jurídico passa a consultar o escritório selecionado e o mesmo escopo autorizado de pastas, inclusive para superusuários. O privilégio da plataforma não contorna o sigilo jurídico. | Não foi criado um mecanismo excepcional de suporte com concessão temporária e justificativa. A administração deve operar pelos vínculos e permissões existentes. |

## Base já existente

- Conta única, múltiplos escritórios, convite com validade, troca de escritório e revogação de vínculo.
- Pastas e processos como entidades separadas; equipe explícita para pastas sigilosas.
- Agenda mensal, semanal e diária; aniversários com link de mensagem revisável no WhatsApp.
- Tarefas em lista e Kanban, prioridades, responsáveis, evidência de conclusão e prazos com conferência humana.
- Arquivos privados, versões imutáveis, hashes e download autenticado. Nova versão não substitui os bytes anteriores.
- Revisão por outra pessoa e publicação explícita de uma versão para a conta de cliente vinculada. CPF/CNPJ não concedem acesso.
- Honorários, parcelas, recebimentos parciais, estornos e separação de recursos do cliente.
- Busca unificada por cadastros, filtros pessoais salvos e importação assistida CSV/Excel de pessoas e processos.
- Notificações internas persistentes de vencimentos e aniversários; autenticação multifator opcional, controle de sessões e auditoria.

## Lacunas que permanecem

**Permissões.** O acesso financeiro continua associado aos papéis Proprietário/Gestor e às regras do plano. Ainda não existe permissão financeira individual independente, exigida nos §§8.1/13.5. Perfis por ação (ver, exportar, compartilhar etc.), negações individuais e funções configuráveis também exigem uma evolução própria. O estoque utiliza sua política de acesso e não amplia acesso ao financeiro jurídico.

**Cadastro e processo.** Solicitação espontânea de participação no escritório, verificação assistida de titularidade de cliente, OAB, campos processuais completos (vara, comarca, classe, distribuição etc.), fases configuráveis, etiquetas e hierarquia de subpastas documentais permanecem parciais ou pendentes. A empresa pode ter mais de uma conta de cliente vinculada; os vínculos e publicações são concedidos individualmente pelos fluxos existentes.

**Colaboração.** Kanban tem estados fixos; subtarefas, recorrência, anexos próprios, automações configuráveis e tarefas derivadas de documentos/prazos com relacionamento explícito não foram implementados. Concluir tarefa não cumpre prazo jurídico automaticamente.

**Editor e assinaturas.** O montador atual gera DOCX e impressão de textos e campos. Editor completo, timbrado, marca-d'água, PDF com fidelidade editorial e solicitação estruturada de assinatura permanecem pendentes. Não há assinatura criptográfica do JUMBI nem integração automática GOV.BR. O portal não recebe arquivos do cliente nesta entrega.

**Notificações e integrações.** Avisos de menções, assinatura, uploads, cobrança e conectores externos ainda não integram a central. E-mail, push e envio automático de WhatsApp não são realizados. Não há consulta automática a tribunais, DataJud, DJEN ou Domicílio Judicial Eletrônico, nem cálculo automático de prazo jurídico. Esses recursos dependem de estudo específico, contratos ou meios autorizados e validação operacional.

**Operação documental.** A validação existente controla extensão, tamanho, integridade e autorização. Não equivale a antivírus. Retenção detalhada por categoria, descarte controlado, exportações assíncronas e busca no conteúdo de arquivos exigem implementação adicional.

## Leitura do mapa

O mapa aceita siglas de UF ou nomes completos, sem diferenciar maiúsculas, acentos ou espaços extras. Brasil, Brazil, BR e BRA são reconhecidos como o país brasileiro. País vazio permite classificar somente quando o estado informado é reconhecido. O filtro de estado restringe a lista; os totais e as cores do mapa continuam mostrando o conjunto definido pelo tipo, pela busca e pelo escopo. “Clientes com pasta acessível” respeita o sigilo atual das pastas. “Todos os cadastros” usa o mesmo acesso da seção Pessoas, inclusive registros ainda sem pasta. Cadastros com relacionamento inativo continuam representados; o status do relacionamento não apaga a localização.

## Arquitetura efetiva

A aplicação permanece um monólito modular Django/Python, com páginas renderizadas no servidor, CSS/JavaScript, PostgreSQL em produção, arquivos privados e serviços systemd. A especificação cita React/TypeScript, DRF, Celery, RabbitMQ e Docker como arquitetura prevista; esses componentes não foram introduzidos nesta entrega. A escolha preserva os fluxos atuais e permite implementar as funcionalidades sem uma reescrita de frontend ou uma fila ainda sem necessidade operacional definida.

## Verificações específicas

A validação deve abranger dados PF/PJ opcionais e formulários existentes; acesso cruzado entre escritórios; sigilo alterado depois do cadastro; revogação de vínculo; perfis somente consulta e cliente; preservação das versões e do histórico; pré-seleção autorizada no portal; comentários escapados; ZIP restrito à pasta solicitada; saldo de estoque não negativo, duplicidade de operações e estornos. As telas novas devem ser verificadas no celular, tablet e desktop, em ambos os temas.
