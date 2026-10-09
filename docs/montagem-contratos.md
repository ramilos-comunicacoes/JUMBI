# Montagem de contratos

Implementação em `apps/contracts`, disponível no plano Max. A referência de fluxo foi lida no código do projeto Autos (`jsveiculos`): biblioteca de modelos, editor com catálogo de variáveis, preenchimento a partir de cadastros e geração para impressão. Nenhum modelo preenchido ou documento real daquele sistema foi importado. Os componentes seguem espaçamento, raios e controles do BJJ, usando as cores do JUMBI.

## Fluxo do módulo

1. A direção ou gestão cria um modelo, do zero ou com a base genérica editável oferecida na tela.
2. O modelo usa texto simples com variáveis do catálogo, como `[[cliente_nome]]` e `[[objeto]]`. Os botões inserem a variável na posição do cursor.
3. Um operador autorizado seleciona pasta e contratante, aciona o preenchimento cadastral, completa os dados e ajusta as cláusulas para aquela montagem.
4. A prévia é renderizada como texto. A validação exige todos os campos efetivamente usados nas cláusulas.
5. Após conferir os dados, o operador gera uma versão. Ela preserva o texto, os valores da entrevista, o nome do modelo, o responsável e os hashes SHA-256.
6. O DOCX privado aparece na pasta jurídica e pode ser baixado. A tela de impressão permite imprimir ou salvar em PDF pelo navegador.
7. Novas redações geram novas versões. Alterar ou arquivar um modelo não altera versões anteriores.

As versões são rascunhos. O módulo não registra assinatura, aprovação jurídica ou envio às partes. As cláusulas da base são uma estrutura neutra para edição profissional; a seleção de texto e das condições pertence ao escritório. Não há geração de aconselhamento jurídico por IA.

## Acesso e preservação

- Direção/gestão: gerenciar modelos e montar contratos. Operação: montar e revisar contratos. Consulta: visualizar e baixar contratos autorizados.
- Pasta sigilosa exige acesso explícito. O perfil de gestão não concede acesso automático.
- Organização e permissões são conferidas na view e novamente no serviço de geração. IDs enviados em formulário não podem trocar o escritório.
- Todas as versões DOCX usam `legal.DocumentVersion`, armazenamento privado e a quota de versões do plano.
- A geração usa transação, bloqueio por escritório, sequência de versões e identificador de operação para evitar duplicação por reenvio.
- Uma falha depois da gravação remove apenas o novo arquivo dessa operação, preservando versões anteriores.
- Texto e valores não são executados como templates, HTML, JavaScript, macros ou expressões. A visualização usa escape e `textContent`; DOCX contém texto OOXML escapado.
- Arquivar o modelo substitui exclusão destrutiva. O histórico de contrato é imutável.
- `visible_contracts` e `visible_revisions` são os filtros de escopo utilizados por exportação e auditoria. Arquivos DOCX também são incluídos pela exportação documental existente.

## Interface de celular

`jumbi-contracts-mobile.css` define composição própria até 720 px: uma coluna para biblioteca e entrevista, controles de 48 px, inputs de 16 px, editor e prévia sequenciais e leitura do documento sem simular uma folha A4 reduzida. A página de impressão possui regras de impressão separadas das regras de tela.

## Validação

`python manage.py test apps.contracts` cobre geração real, integridade do DOCX, imutabilidade, revisão, isolamento entre escritórios, sigilo, permissões, manipulação de IDs, escape de conteúdo, variáveis inválidas, prévia, confirmação dos dados, idempotência, rollback de arquivos, CSRF, download privado, plano e quota. Verificações visuais no navegador complementam os testes de domínio.
