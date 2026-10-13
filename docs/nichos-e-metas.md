# Nichos e metas de desempenho

## Configuração pela administração

Em **Administração JUMBI → Novo escritório**, o superusuário cadastra o escritório, nome e e-mail do responsável, senha inicial, plano, situação da assinatura e uma ou várias áreas de atuação. O catálogo permite combinar quantas áreas forem necessárias, inclusive três ou mais. A criação é atômica: falhas não deixam usuários ou escritórios incompletos. A conta cliente recebe o perfil de direção no próprio escritório, sem privilégios de administrador da plataforma.

O nome do escritório na lista da plataforma abre sua configuração. Somente o superusuário altera os nichos, inclusive no Django Admin. Mudanças ficam no histórico. A ativação da assinatura é manual e não registra um pagamento. Os preços atuais são Start R$ 299,90/mês e Max R$ 599,90/mês; consulte os limites e recursos em planos-e-assinatura.md.

Os códigos são persistidos em `Organization.practice_areas`, uma lista JSON validada pelo catálogo de `apps.core.niches`. `practice_area_choices(organization)` retorna pares `(código, rótulo)`; `practice_area_values(código)` retorna código e rótulo compatível para pastas históricas. Não há conversão destrutiva dos registros existentes.

## Metas

A aba **Metas de desempenho** permite à direção e gestão cadastrar título, descrição, indicador, objetivo positivo, período, responsável opcional e área opcional. Consulta e operação leem metas disponíveis ao seu perfil; somente direção e gestão alteram metas. Metas arquivadas preservam os dados e deixam o resumo do painel.

| Indicador | Como é calculado |
| --- | --- |
| Manual | Total informado pela gestão, acompanhado de evidência e histórico imutável com valor anterior, novo valor, autor e data. |
| Tarefas concluídas | Tarefas atualmente concluídas, pela data efetiva da conclusão dentro do período. Registros legados usam auditoria de conclusão quando disponível; datas ausentes não são inventadas. |
| Pastas abertas no período | Pastas cadastradas durante o período, respeitando área, responsável e permissões de sigilo. |
| Receita recebida líquida | Baixas de receitas menos estornos datados no período; não inclui previsões, despesas ou valores de clientes. Disponível apenas à direção/gestão com plano Max. |

O responsável filtra o dono da tarefa ou pasta. Para receitas, filtra quem registrou a baixa. Sem responsável, o indicador considera o escritório dentro das permissões do usuário. Indicadores automáticos nunca contam eventos futuros. Cada pessoa vê somente os dados permitidos: uma pasta sigilosa sem autorização não contribui para o número apresentado ao usuário.

`dashboard_goals(user, organization, niche='', limit=4)` retorna metas não arquivadas com período vigente, já calculadas para o acesso atual. Cada item contém `goal`, `value`, `percent`, `state` e `is_money`. O percentual visual é limitado de 0 a 100; o total real permanece visível, inclusive se superar a meta. A lista permite consultar outros períodos e metas arquivadas.

## Verificação

A exportação ZIP usa esquema 2 e inclui nichos, configuração das metas, histórico manual, modelos e revisões de contratos com os arquivos privados autorizados. A exportação preserva metas financeiras para direção/gestão mesmo após expiração ou redução do plano, assim como os lançamentos financeiros existentes. Perfis de consulta/operação continuam sem esses dados. A auditoria exportada acompanha as mesmas permissões; contratos de pastas sigilosas sem acesso explícito não entram no pacote. Modelos arquivados usados por contratos autorizados são incluídos para preservar as referências de reconstrução.

Os testes de `apps.core.test_platform_management` e `apps.performance` verificam criação com quatro nichos, validação de senha, rollback, restrição ao superusuário, isolamento entre escritórios, bloqueio de escrita para consulta, CSRF, histórico, datas reais e legado de conclusões, áreas antigas por rótulo, sigilo, receita líquida e bloqueio por plano.

`apps.legal.tests.test_export_extensions` verifica os novos dados, a integridade dos documentos, a exclusão de informações financeiras e sigilosas para perfis sem acesso e a portabilidade após vencimento ou alteração do plano.
