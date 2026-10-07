# Arquitetura inicial

## Principios

- **Monolito modular Django:** um unico deploy e banco PostgreSQL, com limites claros entre os dominios. Isso reduz a complexidade inicial e permite extrair servicos depois, se necessario.
- **Núcleo compartilhado:** identidade, organizações, permissões e auditoria pertencem a `apps/core`.
- **Sistemas independentes:** cada produto tem seu próprio app Django e regras de negócio, sem acessar diretamente as tabelas de outro domínio.

## Mapa de modulos

| Camada | Responsabilidade | Modulos previstos |
| --- | --- | --- |
| Plataforma | Landing institucional, login único, identidade, organizações, sessão, permissões e auditoria | `apps.pages`, `apps.core` |
| Djumbi Jurídico | Clientes, processos, tarefas, documentos, financeiro, equipe e compras | `apps.office` |
| Djumbi Engenharia | Obras, tarefas, fornecedores, compras, financeiro, equipe e evidências | `apps.engineering` |
| Djumbi Agro | Fazendas, talhões, operações, estoque, compras, financeiro, fornecedores e equipe | `apps.agro` |

## Autenticação e contratação

O único ponto de entrada é `/entrar/`. Após autenticar:

1. um superusuário é enviado ao controle central da plataforma;
2. um usuário de cliente tem suas memberships ativas consultadas;
3. a organização contratante define o produto liberado;
4. o usuário é enviado diretamente ao painel correspondente.

As views de cada produto validam novamente o tipo da organização. Conhecer a URL de outro sistema não concede acesso.

## Interface e identidade por organização

A estrutura autenticada permanece carregada enquanto o conteúdo dos módulos é trocado com HTMX. As URLs continuam navegáveis diretamente e o sistema mantém o comportamento HTML tradicional quando JavaScript não está disponível.

Cada `Organization` pode definir logo, cor principal, cor de destaque e cor do menu lateral. A alteração é limitada a proprietários, gestores e superusuários, valida formato/tamanho dos arquivos e registra auditoria.

## Dados e seguranca

O PostgreSQL é o banco oficial. Toda tabela de domínio tem uma organização proprietária e consultas filtradas por ela. Ações sensíveis registram ator, organização, objeto e alteração na trilha de auditoria.

## Isolamento e escala

Cada registro de negócio pertence a uma `Organization`. A organização ativa fica na sessão do usuário e todas as consultas dos sistemas são filtradas por ela; isso impede vazamento entre empresas e permite manter o monólito modular no início. O Django deve permanecer sem estado: sessão em cookie seguro no início e, quando houver mais de uma instância, Redis para sessão, fila e cache. PostgreSQL, arquivos em armazenamento de objetos e workers assíncronos podem escalar separadamente sem mudar os domínios.

## Convencoes de colaboracao

1. Trabalhe em branch curta com prefixo `codex/` ou `feature/`.
2. Atualize a branch antes de iniciar e abra PR para alteracoes compartilhadas.
3. Cada mudanca de schema deve incluir migration e teste correspondente.
4. Segredos ficam exclusivamente em `.env`; nunca entram no Git.
