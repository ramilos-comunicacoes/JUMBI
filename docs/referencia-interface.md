# Referências de interface e aplicação no JUMBI

Revisão: 13/10/2026. Referência: seis capturas de tela do ambiente ADVBOX fornecidas pelo responsável, mostrando Contatos, Agenda, Atividades, CRM e Processos. As capturas serviram para identificar padrões de uso; os dados pessoais nelas presentes não foram transcritos nem importados. A interface conserva a marca, os componentes, os temas e os fluxos do JUMBI.

## Melhorias implementadas

| Área | Comportamento no JUMBI |
| --- | --- |
| Pessoas | Indicadores clicáveis de cadastros com ou sem processo em pasta em andamento, sem duplicar pessoas com vários processos. Busca, tipo, situação do relacionamento, UF, nicho, ordenação e 25/50 registros por página. Lista compacta no desktop e cartões próprios no celular. |
| Perfil da carteira | Distribuição de profissões e faixas etárias calculada sobre todas as pessoas físicas filtradas, com cadastros sem informação identificados. As empresas não entram em gráficos de idade ou profissão. |
| Contato rápido | A ficha abre os dados e as pastas autorizadas. O WhatsApp prepara uma mensagem para revisão e envio manual; nenhum envio ocorre automaticamente. |
| Processos | Indicadores por situação da pasta, distribuição por nicho, responsável, ordenação e paginação. Busca por número, cliente, pasta, órgão ou contraparte. Cada processo mantém o contexto e o link de sua pasta. |
| Agenda | Mês, semana e dia com responsável, nicho, tipo e situação. Navegação conserva os filtros e há alternativa sem JavaScript. Filtros recolhíveis e composição específica no celular. |
| Tarefas | Indicadores de entregas em aberto, atrasadas e concluídas no mês. Atalhos filtram o Kanban; recortes de hoje e dos próximos sete dias mantêm responsáveis, prioridades e nichos. As conclusões usam a data real registrada. |
| Relacionamento | Quadro e lista, filtros por responsável, etapa, nicho e atenção, ordenação e atalhos de indicadores. Contagens e estimativas das colunas abrangem todos os resultados; a interface informa quantos cartões pertencem à página atual. |
| Orientação | Guia “Como usar o JUMBI”, ajuda recolhível e explicação do escopo dos indicadores. Os caminhos levam aos módulos reais e respeitam o perfil e o plano. |

## Significado dos indicadores

- **Processo em pasta em andamento** significa que existe um processo cadastrado em uma pasta com situação Em andamento que o usuário pode consultar. O JUMBI não deduz a fase do tribunal nem exibe processos sigilosos inacessíveis nesses números.
- Em Pessoas, os indicadores mantêm busca, tipo, relacionamento, UF e nicho; a seleção de vínculo com processo afeta gráficos e lista. Nos Processos, os indicadores mantêm busca, responsável e nicho; selecionar uma situação afeta a lista e a distribuição.
- Na Agenda, **Concluídos** são tarefas concluídas e prazos cumpridos. **Encerrados** são compromissos cujo horário de término passou, sem afirmar que foram realizados. **Atrasados** considera somente tarefas e prazos em aberto com vencimento anterior a hoje. Aniversários seguem os clientes autorizados e o nicho, independentemente do responsável ou da situação dos eventos.
- No Kanban, os indicadores respeitam busca, responsável, prioridade e nicho; o recorte temporal afeta os cartões. Tarefas antigas concluídas sem uma data de conclusão não são atribuídas artificialmente ao mês atual.
- No Relacionamento, os indicadores respeitam busca, responsável e nicho, independentemente da etapa e da atenção selecionadas. Seus atalhos substituem esses dois últimos filtros. Estimativas comerciais não são recebimentos, e ganhar uma oportunidade não cria uma baixa financeira.
- O filtro de nicho em Pessoas e Relacionamento utiliza vínculos com pastas acessíveis. Um contato sem pasta pode aparecer no conjunto geral e ficar fora de um nicho específico.

## Limites preservados

Não foram criados gráficos de origem de aquisição, comparações mensais de encerramento, andamentos externos, produtividade por pontuação ou fases processuais sem dados que os sustentem. A captura de uma interface não comprova integrações ou regras internas do produto de referência. Recursos pendentes continuam relacionados em `docs/requisitos-v02.md` e `docs/auditoria-documentacao.md`.

As novas consultas validam filtros, respeitam o escritório e as pastas visíveis e usam ordenações permitidas. Os testes de domínio e HTTP cobrem isolamento, sigilo, paginação, datas reais, filtros malformados e preservação de permissões. A confirmação de implantação e os resultados finais estão em `docs/operacao-piloto.md`.
