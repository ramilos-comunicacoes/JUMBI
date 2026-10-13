# Honorários e assessoria mensal

O módulo `/honorarios/` está disponível no plano Max para direção e gestão. Cada acordo exige uma pasta autorizada e um cliente do escritório; quando a pasta já tem cliente, o vínculo deve ser o mesmo. O sigilo da pasta continua valendo para gestores e superusuários.

- **Honorários parcelados:** o valor informado é o total do acordo. A divisão é em centavos exatos, com o restante distribuído pelas primeiras parcelas. R$ 100,00 em três parcelas produz R$ 33,34 + R$ 33,33 + R$ 33,33.
- **Assessoria mensal:** o valor informado é de cada mês. O usuário escolhe de 1 a 36 meses; todos os lançamentos desse horizonte são registrados após a confirmação.
- Datas mantêm o dia do primeiro vencimento. Caso a primeira data seja o último dia do mês, os demais vencimentos também serão no último dia de cada mês. Um início em 30/01 resulta em 28/02 (29 em ano bissexto), depois 30/03; início em 31/01 resulta em último dia de fevereiro, depois 31/03.

A tela permite conferir a prévia sem gravar dados. O formulário exige confirmação e seu identificador de operação é idempotente: a repetição do mesmo pedido não duplica acordos nem lançamentos. Alterar o conteúdo usando a mesma chave gera erro. Criação ocorre em uma transação com bloqueio por escritório.

Cada parcela se vincula a um `FinanceEntry` de receita. As baixas parciais, os estornos com motivo e seus históricos usam os serviços financeiros existentes. Não são criados registros de recebimento no cadastro do acordo, nem misturados valores pertencentes a clientes. O detalhe mostra previsto, recebido líquido e saldo por parcela. A impressão do cronograma não é recibo de pagamento.

O acordo e as parcelas preservam o cronograma original. O helper `validate_fee_entry` chamado por `FinanceEntry.clean` impede alterar valor, vencimento, tipo e pasta dos lançamentos vinculados. Não há cancelamento, renegociação, renovação automática, cobrança bancária, boleto ou PIX automático nesta versão; uma renovação exige novo acordo explícito.

## Integração e portabilidade

App: `apps.fees`. Rotas: `fees:overview`, `fees:create`, `fees:detail`. Menu: chave `fees`, limitado a Max + owner/manager. A verificação de acesso também está no serviço, independente do menu.

Exportação usa `visible_plans(actor, organization, for_export=True)` e `visible_installments(...)`, que preservam tenant, role e sigilo, permitindo portabilidade após expiração da assinatura. Campos: FeePlan `title,matter_id,client_id,kind,amount,total_amount,periods,first_due_date,notes,created_by_id,created_at`; FeeInstallment `plan_id,entry_id,number,due_date,amount`. Chaves de requisição e hashes internos não precisam compor o pacote. Eventos de auditoria `fees.plan_created` são visíveis apenas a quem ainda pode consultar seu acordo.

## Verificações

`python manage.py test apps.fees` cobre centavos, fim de mês, ano bissexto, datas limite, faixa de meses, transação, repetição de pedido, alterações na mesma chave, Max, permissões, cliente/tenant/sigilo, CSRF, escape de conteúdo, prévia sem escrita, imutabilidade, baixas parciais e estornos. O teste de bloqueio concorrente deve usar PostgreSQL; SQLite não comprova bloqueios de linha.
