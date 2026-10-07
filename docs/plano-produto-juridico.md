# Jumbi — plano de produto jurídico

## Visão

O Jumbi é uma plataforma única de gestão jurídica, configurável por área de atuação. O núcleo comum concentra clientes, casos, agenda, documentos, equipe, financeiro, compras, acessos, identidade visual e auditoria. As particularidades de cada especialidade entram como tipos de demanda, fluxos, documentos, campos e automações configuráveis.

Essa arquitetura evita manter sistemas duplicados e permite que um escritório multidisciplinar trabalhe em uma única base com segregação por organização, função e nível de sigilo.

## Base entregue

- 21 áreas jurídicas e 72 tipos de demanda.
- Classificação do caso por área, tipo, natureza, fase, prioridade e status.
- Parte contrária, tribunal/órgão, número do processo/protocolo e resumo estratégico.
- Checklists iniciais gerados a partir do tipo de demanda e vinculados ao caso.
- Atividades classificadas como tarefa, prazo, audiência, compromisso ou acompanhamento.
- Prioridade operacional de atividades.
- Busca por área ou tipo de demanda.
- Sigilo visível somente para direção e gerência.
- Validação dos vínculos de cliente, caso e organização.
- Auditoria da criação do caso e da geração do checklist.
- Índices de banco para carteira, visibilidade, prazos e fila de trabalho.

## Áreas cobertas

Civil; Família e Sucessões; Trabalhista; Previdenciário; Criminal; Empresarial e Societário; Tributário; Consumidor; Imobiliário; Administrativo e Direito Público; Propriedade Intelectual e Marcas; Digital, Tecnologia e LGPD; Ambiental; Agrário; Eleitoral; Contratos; Arbitragem e Mediação; Saúde; Bancário e Financeiro; Internacional e Migratório; Compliance e Investigações.

## Próximas frentes

### 1. Entrada e relacionamento

- CRM de potenciais clientes e origens.
- Formulários de triagem por área.
- Checagem de conflito de interesses.
- Propostas, contratos e aceite eletrônico.
- Conversão de oportunidade em cliente e caso.

### 2. Carteira processual brasileira

- Partes, representantes, polos e múltiplos números.
- Instâncias, tribunais, órgãos, comarcas e assuntos.
- Movimentações e linha do tempo imutável.
- Captura de intimações e publicações por integrações autorizadas.
- Agenda legal com regras versionadas e validação humana.
- Audiências, sessões, sustentações e diligências.

### 3. Documentos e conhecimento

- Modelos com campos dinâmicos e versionamento.
- Geração de documentos a partir do caso.
- Assinatura eletrônica por provedor.
- OCR, pesquisa e classificação.
- Base de precedentes, teses, pareceres e cláusulas.
- Política de retenção e descarte.

### 4. Comunicação e portal

- Portal seguro do cliente.
- Solicitação estruturada de documentos.
- Mensagens e atualizações do caso.
- Registro de e-mail e WhatsApp mediante integrações oficiais.
- Preferências de comunicação e consentimentos.

### 5. Financeiro jurídico

- Contratos de honorários fixos, recorrentes, por hora e de êxito.
- Timesheet, despesas reembolsáveis e centros de custo.
- Contas a pagar e receber, conciliação e inadimplência.
- Repasse, comissionamento e divisão de honorários.
- Provisionamento e cenários de risco para departamentos jurídicos.
- Integração contábil por API.

### 6. Gestão, dados e automação

- Painéis por área, responsável, cliente, fase e resultado.
- Capacidade e produtividade sem métricas abusivas.
- SLA interno e gargalos.
- Construtor visual de fluxos, campos e permissões.
- Webhooks, API pública e integrações.
- Assistência por IA com referências, aprovação humana, trilha de auditoria e isolamento de dados.

## Regras permanentes de engenharia

- Isolamento por organização em todas as consultas e mutações.
- Menor privilégio por função e proteção adicional para casos sigilosos.
- Auditoria de ações sensíveis.
- Nenhum prazo legal criado sem fonte, regra versionada e validação profissional.
- Backups testados, criptografia em trânsito e segredos fora do código.
- Migrações reversíveis e publicação com backup anterior.
- Acessibilidade, experiência responsiva e navegação sem recarga integral.
- Testes de autorização, isolamento, regressão e fluxos críticos em cada entrega.
