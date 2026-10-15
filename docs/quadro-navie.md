# Quadro de tarefas: referência Navie Hospedagens

## Origem e autoria

O quadro foi consultado diretamente no código do Navie Hospedagens, em
`/var/www/apps/navievibe`, em 15/10/2026, com autorização do proprietário.
A inspeção foi somente leitura e não acessou banco, mídias, arquivos de ambiente
ou dados de hóspedes. A composição visual é adaptada ao JUMBI; as regras de
negócio, os registros e as permissões continuam sendo os do sistema jurídico.

Fontes de referência no Navie:

- `hoteis/templates/hoteis/atividades/partials/kanban.html`: colunas e arraste.
- `hoteis/templates/hoteis/atividades/partials/card_tarefa.html`: cards e ações.
- `hoteis/templates/hoteis/atividades/partials/modal_tarefa.html`: criação e edição.
- `hoteis/templates/hoteis/atividades/partials/calendario.html`: modo calendário.
- `hoteis/templates/hoteis/partner_dashboard.html`: controles no cabeçalho e
  subcabeçalho mobile; área `#atividades-content`.
- `hoteis/templates/hoteis/base_partner.html`: tokens de cores, vidro dos campos,
  barras de rolagem e dependências de interação.
- `hoteis/views.py`, `hoteis/models.py` e `hoteis/urls.py`: fluxo das tarefas.

### SortableJS

`static/vendor/sortable/Sortable.min.js` é a biblioteca **SortableJS 1.15.2**, a
mesma versão local usada pelo Navie, com o cabeçalho de autoria preservado.
O JUMBI serve o arquivo localmente, sem depender de CDN para o arraste.

Copyright (c) 2019 All contributors to Sortable. Licença MIT, incluída em
`static/vendor/sortable/LICENSE` e conferida no
[arquivo oficial da versão 1.15.2](https://github.com/SortableJS/Sortable/blob/1.15.2/LICENSE).
Projeto oficial: [SortableJS/Sortable](https://github.com/SortableJS/Sortable).

## Composição transportada

O Navie apresenta quatro grandes colunas: Atrasadas, A Fazer, Progresso e
Concluído. Usa fundos translúcidos discretos, bordas e marcadores coloridos,
títulos compactos com contador e cards arredondados. O card tem prioridade no
topo, título e descrição no centro, responsável e prazo no rodapé. A criação e
a edição são acessadas sem sair do contexto do quadro.

No desktop, a referência tem quatro colunas em grade. No celular, cada coluna
ocupa a maior parte da largura da tela, com rolagem lateral e encaixe por coluna;
a lista dentro de cada coluna pode rolar verticalmente. Os controles do modo
de exibição ficam em uma subbarra própria no mobile.

Medidas de referência: raio de 16px nas colunas/cards, distância de 24px entre
colunas, padding de 20px nos cards e nos cabeçalhos, gap de 12px nas listas,
avatar de 28px e barra de rolagem de 5px. O JUMBI ajusta a tipografia e as áreas
de toque para legibilidade e acesso por teclado, mantendo sua personalização
de marca e os temas claro/escuro.

## Adaptação dos estados jurídicos

Os quatro grupos visuais não removem estados existentes nem alteram o histórico:

| Coluna do JUMBI | Registros apresentados |
| --- | --- |
| Atrasadas | Tarefas em aberto com prazo vencido; calculado automaticamente |
| A fazer | Estado `todo`, excluindo as atrasadas |
| Em andamento | Estados `doing`, `in_review` e `blocked`, excluindo as atrasadas |
| Finalizadas | Estados `done` e `cancelled`, identificados individualmente |

Revisão, bloqueio, conclusão e cancelamento continuam explícitos no registro.
Agrupar a apresentação não transforma uma tarefa cancelada em concluída nem
dispensa as validações de conclusão e de permissão.

## Arraste e ordenação

A referência Navie usa SortableJS com animação de 150ms, fantasma translúcido,
retardo de 150ms somente no toque e tolerância de movimento de 5px. Isso permite
pressionar para arrastar e continua permitindo rolagem normal no celular.

No Navie, apenas a troca de coluna é persistida. A reordenação manual dentro da
mesma coluna não possui campo de posição no banco. O JUMBI mantém sua ordenação
por prazo; a posição no quadro não representa uma ordem manual persistente.
As mudanças de etapa passam pela validação e auditoria do JUMBI, com proteção
contra atualização concorrente e retorno ao estado anterior quando a operação
não é aceita.

## Regra que não deve ser copiada

O handler `partner_mudar_status_tarefa` do Navie aceita arrastar para Atrasadas e
altera a data de vencimento para ontem. **Essa regra não se aplica ao JUMBI.**
No sistema jurídico, Atrasadas é uma visão automática e não pode receber um
arraste que reescreva o prazo. Alterar um prazo continua exigindo a edição
explícita do registro, com suas validações e trilha de auditoria.

Também não são transportadas a exclusão permanente do Navie, as relações com
hotel/quarto/reserva nem as regras de autorização da hospedagem. O JUMBI mantém
o isolamento por empresa, os limites de acesso, os vínculos jurídicos e o
histórico das tarefas.
