# Exemplos para o mapa de clientes

O comando opcional `seed_client_map_demo` cadastra sete pessoas fictícias para explorar os filtros e a distribuição geográfica do mapa. Ele funciona somente nos escritórios de demonstração expressamente permitidos e nunca completa endereços de contatos existentes.

## Dados criados

Todos os novos nomes começam com **[DEMONSTRAÇÃO] Mapa ·** e as observações identificam os dados como fictícios.

| UF | Cidade | Novos cadastros |
| --- | --- | ---: |
| CE | Fortaleza | 2 |
| SP | São Paulo | 1 |
| RJ | Rio de Janeiro | 1 |
| PE | Recife | 1 |
| DF | Brasília | 1 |
| RS | Porto Alegre | 1 |

O país informado é Brasil. E-mail, telefone, CPF/CNPJ, CEP, rua, número, complemento, bairro e nascimento permanecem vazios. O comando não cria pastas, processos, vínculos de portal, publicações, lançamentos financeiros ou pagamentos.

## Uso

Prévia local, sem gravar:

```powershell
python manage.py seed_client_map_demo --organization jumbi-demonstracao-local --email demo@jumbi.local
```

Cadastro local, após conferir a prévia:

```powershell
python manage.py seed_client_map_demo --organization jumbi-demonstracao-local --email demo@jumbi.local --apply
```

O outro par permitido é `--organization jumbi-demonstracao --email demo@jumbi.nabio.pro`. O uso no servidor deve ser executado apenas no ambiente JUMBI correto, após a publicação das migrações e a conferência da prévia.

## Proteções

- O escritório deve estar ativo, no segmento jurídico, com assinatura **Max em demonstração vigente**. Essa restrição é do comando de preparação; o mapa do produto está incluído nos planos Start e Max.
- O e-mail precisa corresponder exatamente ao escritório permitido, e a pessoa deve estar ativa como direção ou gestão desse escritório.
- O modo padrão é somente leitura. `--apply` é obrigatório para cadastrar.
- Todos os nomes reservados são conferidos antes de gravar. Um conflito recusa o pacote inteiro, inclusive se o nome existente diferir apenas por maiúsculas e minúsculas.
- Os sete cadastros, os respectivos eventos de auditoria e o marcador de conclusão são gravados na mesma transação, com bloqueio do escritório.
- Depois da primeira execução concluída, o marcador impede qualquer recriação ou atualização. Alterações feitas pelo usuário nos exemplos são preservadas. O comando não repara cadastros parciais nem sobrescreve dados.

O mapa usa os registros do escritório para calcular os totais. Esses exemplos tornam a distribuição visível na demonstração sem preencher dados pessoais ou localizações de clientes reais.
