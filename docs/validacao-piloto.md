> Registro histórico da primeira versão local. Para o estado publicado, consulte [operação do JUMBI](operacao-piloto.md).

# Validação da primeira evolução jurídica

Data: 07/10/2026. Execução local com Python 3.11, Django 5.2.18 e SQLite. Dados exclusivamente fictícios.

## Resultado

- 55 testes automatizados passaram: domínio jurídico/financeiro, telas e permissões, cadastro/autenticação/equipe.
- `manage.py check`: nenhuma ocorrência.
- `makemigrations --check --dry-run`: nenhuma diferença de esquema pendente.
- Migrações aplicadas em banco local, incluindo preenchimento individual de chaves UUID em baixas preexistentes.
- Assets coletados com `collectstatic`.
- Fluxo real em Chrome: cadastro de escritório, pessoa, pasta consultiva sem processo, prazo manual, conferência, conclusão de tarefa, revisão de prazo com motivo, upload/download privado, recebimento parcial e estorno.
- Conferida a separação entre conclusão de tarefa e cumprimento do prazo. Revisão exige nova conferência.
- Exemplo financeiro de R$ 1.000,00 com baixa de R$ 350,00 e saldo de R$ 650,00; estorno recupera saldo integral sem apagar registros. Testes cobrem repetição do mesmo pedido sem duplicação e rejeição de dados divergentes para a mesma chave.
- Download anônimo bloqueado; testes verificam outros escritórios, pastas sigilosas, revogação, perfis de consulta, exportação ZIP/JSON e adulteração de relações.
- ZIP inspecionado com validação dos hashes SHA-256, relações, revisão de prazo e histórico de pagamento/estorno.
- 14 rotas principais conferidas em navegador, além dos testes HTTP dos formulários; nenhum erro JavaScript.
- Layout revisado em desktop, temas claro/escuro e celular. Sem overflow horizontal da página em 360, 390 e 720 px; tabelas têm rolagem própria. Menu mobile abre, fecha por Escape e controla foco.
- Verificação dos arquivos do projeto não encontrou a senha SSH fornecida pelo usuário. `.env`, arquivos privados, banco e ferramentas temporárias estão ignorados pelo Git.

## Limites desta evidência

Os testes locais usam SQLite; não comprovam concorrência real com locks PostgreSQL. A CI com PostgreSQL 14 está preparada, mas não foi executada no GitHub nesta entrega. A revisão de segurança da configuração de produção apontou somente os avisos de HSTS para subdomínios e preload: ambos permanecem desativados deliberadamente para não ampliar a política do host.

Não houve publicação, mudança de DNS/proxy, migração de dados antigos, teste de restauração da produção ou envio do código ao GitHub. O servidor original permanece preservado. A nova interface e os fluxos são uma base de piloto, não a totalidade das fases do estudo.
