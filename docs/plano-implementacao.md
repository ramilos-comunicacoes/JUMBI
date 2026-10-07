# Plano de implementação

## Fase 0 — Fundação (concluída)

- [x] Repositorio remoto conectado.
- [x] Projeto Django e configuração PostgreSQL por variáveis de ambiente.
- [x] Landing page e pontos de entrada dos superapps.
- [x] Documentação de arquitetura e colaboração.
- [x] Contas por organização, login seguro e painel protegido.
- [x] Controle mestre para superusuário, organizações e provisionamento de acessos.
- [x] Interface responsiva com temas claro/escuro.

## Fase 1 — Plataforma comum (protótipo funcional)

- [x] Login único com roteamento automático pelo produto contratado.
- [x] Isolamento multiempresa e bloqueio entre Jurídico, Engenharia e Agro.
- [x] Contas, organizações, equipes, papéis e permissões.
- [x] Layout autenticado, controle central e auditoria.
- [x] Personalização de marca por organização e navegação interna com HTMX.
- [x] Testes automatizados dos fluxos de acesso, isolamento e CRUD.
- [ ] Configurar CI, monitoramento, backups testados e homologação separada.

## Fase 2 — Djumbi Jurídico

- [x] Clientes, processos, tarefas, documentos, financeiro, equipe e compras.
- [x] Alteração auditada do status de tarefas.
- [ ] Agenda processual, alertas de prazos e relatórios jurídicos avançados.

## Fase 3 — Djumbi Engenharia

- [x] Obras, tarefas, fornecedores, compras, financeiro, equipe e evidências.
- [x] Fluxo auditado de situação de obras.
- [ ] Medições, contratos, estoque por obra e relatórios físico-financeiros avançados.

## Fase 4 — Djumbi Agro

- [x] Fazendas, talhões, operações, estoque, compras, financeiro, fornecedores e equipe.
- [x] Alteração auditada do status de operações.
- [ ] Safras completas, maquinário, rebanhos e indicadores de produção.

## Critério para iniciar cada fase

Cada evolução de módulo começa após a documentação funcional trazer: usuários envolvidos, problema resolvido, dados obrigatórios, regras de permissão, telas/fluxos e critérios de aceite.
