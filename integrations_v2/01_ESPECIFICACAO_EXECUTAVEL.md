# JUMBI — Integrações judiciais: especificação para implementação
Versão: 2.0 • Data de referência: 14/10/2026
Produto: Jumbi • Destino previsto: https://jumbi.nabio.pro
Stack do projeto: Django, API REST, PostgreSQL; aproveitar a interface e as filas existentes. Para uma base nova, manter a direção React/TypeScript e Celery/RabbitMQ do planejamento.

## 0. Ordem de execução para o Codex
Implemente este escopo no repositório real do Jumbi. Não entregue apenas uma nova proposta de arquitetura. Inspecione o projeto, identifique o que já existe, desenvolva as partes autorizadas, rode testes, registre resultados e documente apenas os bloqueios externos efetivos.

Leia primeiro esta especificação e 02_CATALOGO_APIS.json. Use 03_REGISTRO_TRIBUNAIS.json para o inventário, 04_CHECKLIST_ACEITE.md para testes e 05_PENDENCIAS_EXTERNAS.md para habilitações. Os scripts do pacote são ferramentas de inspeção e componentes de referência; não são um sistema Jumbi já implementado nem conectores judiciais homologados.

Preserve o trabalho existente, as decisões aplicáveis do AGENTS.md do repositório, a pasta jurídica, o isolamento entre escritórios e os ambientes. Não clone nem publique no repositório de outro produto apenas porque seu endereço aparece em uma conversa antiga. O domínio do produto é jumbi.nabio.pro; a existência desse nome não informa IP, provedor DNS, credenciais ou repositório. Use o documento operacional de acesso já fornecido para o projeto, sem copiar seus segredos para Git, frontend ou logs.

Avance nas decisões locais reversíveis dentro deste escopo. Não interrompa toda a implementação porque uma credencial externa ainda não foi fornecida: conclua modelos, telas, permissões, filas, testes com dados sintéticos e importação manual. Registre a capacidade afetada como pendente. Solicite apenas o dado realmente indisponível, sem tratá-lo como requisito para as partes independentes.

Não confunda dois produtos de nome semelhante: Codex, usado pelo usuário para desenvolver código, não é a plataforma Codex/datalake do CNJ. O uso do primeiro não concede acesso ao segundo.

Resultado funcional esperado:
Um escritório configura um monitoramento; uma fonte autorizada é consultada; resultados e falhas são registrados; uma publicação entra na triagem; o profissional confirma o caso e a providência; uma atividade é atribuída; o prazo é conferido; o relatório diário pode ser gerado; a gestora acompanha o histórico. Um segundo escritório não consegue acessar nenhum registro privado dessa operação.

Escopo da automação:
Automatizar a preparação técnica, coleta pública permitida, validação de contrato, desenvolvimento, testes e operação interna. Não autorizar automaticamente registro de ciência, peticionamento, aceitação de termos em nome de terceiros, gastos, credenciamentos com declarações pessoais, alterações destrutivas ou acesso além dos poderes concedidos. Essas operações exigem permissões, habilitação e ação específica do responsável.
