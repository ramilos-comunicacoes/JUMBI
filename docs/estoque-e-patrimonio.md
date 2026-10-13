# Estoque e patrimônio

O módulo organiza materiais consumíveis e bens duráveis do escritório. Reaproveita os conceitos de categorias, fornecedores, compras, lotes e movimentações do Navie Hospedagens, adaptados ao isolamento por escritório e às permissões do JUMBI. Os dados operacionais dos outros sistemas não são importados.

## Acesso e separação dos registros

- Disponível no **plano Max**, para usuários ativos com perfil **Direção/Proprietário** ou **Gestão**.
- Operadores, usuários de consulta e clientes do portal não acessam os registros de estoque ou patrimônio.
- Cada registro pertence a um escritório. Materiais, categorias, lotes, fornecedores, compras e responsáveis são conferidos novamente ao salvar.
- Quantidades e valores não são compartilhados entre escritórios. Um usuário que participa de vários escritórios trabalha no escritório selecionado.

## Materiais e estoque

Cadastre uma categoria quando ela ajudar a organizar os itens. Em seguida, cadastre o material com código interno exclusivo, nome, unidade, localização e quantidade mínima desejada. O saldo inicial não é digitado diretamente no cadastro: registre uma entrada para preservar sua origem.

As unidades disponíveis são unidade, quilograma, litro, pacote, caixa e metro. Quantidades admitem até três casas decimais. Depois da criação de um lote, a unidade do material é preservada; para outra unidade, crie outro material e registre a movimentação correspondente após conferência.

O saldo total de um material é a soma dos seus lotes. Não existe transferência automática de saldo entre lotes. Desativar um material impede novas movimentações normais e novas compras para esse item, preservando os saldos e o histórico; reative-o para voltar a movimentá-lo. Estornos corretivos preservam o vínculo com sua operação original.

### Lotes e validade

Cada entrada usa um lote existente ou cria um lote identificado por código, com validade opcional. O código e a validade do lote são preservados após seu cadastro. Duas entradas do mesmo material e código só podem usar a mesma validade.

Os avisos de validade consideram apenas **lotes com saldo positivo**. São separados os vencidos e os que vencem nos próximos 30 dias. Um lote inteiramente consumido ou baixado não continua gerando aviso. A validade no dia atual ainda não é considerada vencida.

O consumo de lote vencido é bloqueado. Para descarte, registre perda com o motivo correspondente. A contagem física continua disponível para conferir a quantidade efetivamente encontrada. O sistema não escolhe automaticamente um lote: a pessoa responsável indica qual lote foi usado.

### Movimentações

| Operação | Quantidade informada | Efeito |
| --- | --- | --- |
| Entrada | Quantidade recebida, maior que zero | Acrescenta ao lote selecionado ou ao novo lote. |
| Consumo | Quantidade utilizada, maior que zero | Reduz somente o lote selecionado. |
| Perda | Quantidade descartada, maior que zero | Reduz somente o lote selecionado, com motivo. |
| Contagem física | Saldo total encontrado no lote, inclusive zero | Registra a diferença entre o saldo anterior e a contagem. |
| Estorno | Operação original e motivo | Compensa exatamente a variação da operação original. |

Toda movimentação registra autor, data e hora, motivo, variação e saldo do lote após a operação. Uma contagem de 4 unidades em um lote com saldo 10 registra uma diferença de −6; informar 0 zera o lote. Conferir o mesmo saldo também deixa um registro de contagem.

O saldo nunca pode ficar negativo. Uma saída de 6 unidades de um lote com saldo 5 será recusada, mesmo que outro lote tenha unidades disponíveis. Reenvios da mesma operação não repetem a movimentação; reutilizar sua identificação com dados diferentes é recusado.

As movimentações não são editadas nem apagadas. Uma movimentação só pode ser estornada uma vez, e um estorno não pode ser estornado. Estornar uma entrada exige que o lote ainda tenha saldo suficiente; se parte foi consumida, confira o histórico e registre a correção adequada, sem apagar as saídas anteriores.

O alerta de estoque baixo aparece para materiais ativos cujo saldo total seja igual ou inferior ao mínimo configurado. Ele não gera pedido de compra automaticamente.

## Compras e recebimento

1. Cadastre o fornecedor, se desejar identificá-lo na compra.
2. Crie a compra com referência ou nota fiscal, data e entre 1 e 30 itens. Cada item informa material, quantidade, custo unitário, lote e validade opcional.
3. Confira os dados. A compra fica **Aguardando recebimento** e ainda não altera o estoque.
4. Após receber e conferir fisicamente os materiais, confirme o recebimento. Todos os itens entram no estoque na mesma transação. Se um item não puder entrar, nenhuma entrada dessa compra é efetivada.

Custos admitem até duas casas decimais e podem ser zero para fornecimentos sem custo. O subtotal de cada item é quantidade × custo unitário, arredondado para centavos. O total da compra soma esses subtotais. O mesmo material e lote deve aparecer em uma única linha da compra.

Os itens da compra são preservados depois do cadastro. Antes do recebimento, uma compra incorreta pode ser cancelada com justificativa e cadastrada novamente. Compras canceladas não podem ser recebidas. Compras já recebidas não são canceladas: correções nas entradas usam estornos, mantendo o recebimento original e sua trilha de auditoria.

Receber a mesma compra novamente não duplica o estoque. Conflitos de validade, materiais desativados ou quantidades acima do limite interrompem o recebimento integralmente.

**Compra, recebimento e estorno de estoque não criam despesas, baixas ou pagamentos no financeiro.** Os custos são informativos para controle administrativo. O registro financeiro, quando necessário, é realizado e conferido no módulo financeiro.

## Patrimônio do escritório

Bens duráveis, como computadores, mobiliário e equipamentos, têm cadastro separado dos materiais consumíveis. Cada bem possui etiqueta patrimonial exclusiva, nome, categoria opcional, número de série, localização, responsável, data e valor de aquisição opcionais, situação e observações.

O responsável deve ser uma pessoa ativa da equipe interna do mesmo escritório. Clientes do portal não podem receber a responsabilidade por um bem. As situações disponíveis são **Disponível**, **Em uso**, **Em manutenção** e **Baixado**.

Toda inclusão ou alteração pede um motivo e registra uma fotografia dos dados antes e depois, com autor e data. Assim, mudanças de sala, responsabilidade ou situação continuam consultáveis. Bens baixados permanecem no histórico. O valor de aquisição é informativo e não registra pagamento, depreciação contábil ou despesa automaticamente.

## Histórico, proteção e portabilidade

As escritas são atômicas e serializadas por escritório, com conferência do saldo atual. Movimentações e eventos patrimoniais são imutáveis. O recebimento de compras e os reenvios de operações usam identificadores que impedem duplicação acidental.

A exportação autorizada do escritório inclui categorias, fornecedores, materiais, lotes, movimentações, compras, itens, patrimônio e histórico patrimonial. Direção e gestão continuam podendo exportar seus registros históricos após expiração ou redução do plano; os controles de usuário, escritório ativo e perfil permanecem aplicados. O ZIP de uma pasta jurídica não inclui o estoque ou o patrimônio geral do escritório.

## Limites desta versão

O comando administrativo `seed_inventory_demo --organization jumbi-demonstracao --email demo@jumbi.nabio.pro` mostra uma prévia de exemplos fictícios. Somente `--apply` grava. Ele aceita apenas os pares exatos de escritório/usuário demo de produção ou local, exige assinatura Max/demo vigente e perfil de direção/gestão. Cria dois materiais, saldos iniciais, uma compra pendente e dois equipamentos, todos identificados como demonstração. Não sobrescreve cadastros, não reabastece após testes e não gera lançamentos financeiros. Escritórios reais são recusados.

Não há emissão de nota fiscal, integração com fornecedores, leitura de código de barras, escolha automática FIFO/FEFO, recebimento parcial de compras, ordens de manutenção, cálculo de depreciação ou conciliação contábil automática. As baixas e os recebimentos dependem de conferência humana. O módulo trata o inventário administrativo do escritório; não substitui um procedimento jurídico de inventário sucessório.
