Fontes e limites de verificação
Pesquisa: 14/10/2026. Consulta documental a fontes oficiais; sem autenticação judicial nem protocolo. A fonte do inventário estadual é o estudo v1 fornecido no projeto, preservado em reference/estudo_v1.md. O inventário não foi integralmente repesquisado nesta revisão.
A01 — CNJ — orientações de integração DJEN; bases de homologação e produção
[https://www.cnj.jus.br/programas-e-acoes/processo-judicial-eletronico-pje/comunicacoes-processuais/orientacoes-aos-tribunais/](https://www.cnj.jus.br/programas-e-acoes/processo-judicial-eletronico-pje/comunicacoes-processuais/orientacoes-aos-tribunais/)
Fonte oficial do endereço; o texto também trata de envio reservado a tribunais.
A02 — CNJ — Swagger DJEN 1.0.4
[https://hcomunicaapi.cnj.jus.br/swagger/index.html](https://hcomunicaapi.cnj.jus.br/swagger/index.html)
Rotas públicas confirmadas documentalmente; YAML não recuperado nesta execução.
A03 — PDPJ — Domicílio Judicial Eletrônico
[https://docs.pdpj.jus.br/servicos-negociais/domicilio-judicial-eletronico/](https://docs.pdpj.jus.br/servicos-negociais/domicilio-judicial-eletronico/)
Credenciamento CNPJ, token, representação, tenantId e efeitos de ciência; conferir Swagger após habilitação.
A04 — PDPJ — autenticação SSO
[https://docs.pdpj.jus.br/servicos-estruturantes/autenticacao-sso/](https://docs.pdpj.jus.br/servicos-estruturantes/autenticacao-sso/)
Endereços de token e client_credentials; cadastro do cliente junto ao CNJ.
A05 — TJBA — Web Service PJe 1º e 2º graus
[https://www.tjba.jus.br/portal/web-service/](https://www.tjba.jus.br/portal/web-service/)
Quatro WSDLs publicados; leitura do WSDL e chamadas autenticadas não executadas.
A06 — TJRJ — acesso automatizado por sistemas externos
[https://portaltj.tjrj.jus.br/secretarias-gerais/sgtec/transparencia-ativa/acesso_automatizado_por_sistemas_externos](https://portaltj.tjrj.jus.br/secretarias-gerais/sgtec/transparencia-ativa/acesso_automatizado_por_sistemas_externos)
Serviço MNI e duas APIs de metadados; não são a mesma capacidade.
A07 — PDPJ — guia do serviço de Notificações
[https://docs.pdpj.jus.br/servicos-estruturantes/notificacoes/guia-usuario-notificacoes/](https://docs.pdpj.jus.br/servicos-estruturantes/notificacoes/guia-usuario-notificacoes/)
HMAC SHA-256 hexadecimal no cabeçalho X-PDPJ-Webhook-Signature; subscrição depende do escopo.
A08 — PDPJ — petição intercorrente
[https://docs.pdpj.jus.br/servicos-negociais/portal-servicos/pet-intercorrente/](https://docs.pdpj.jus.br/servicos-negociais/portal-servicos/pet-intercorrente/)
Exemplos para consumo e callback por tribunais; não são API aberta de peticionamento do Jumbi.
A09 — PDPJ — Tabelas Processuais Unificadas
[https://docs.pdpj.jus.br/servicos-estruturantes/tpu/](https://docs.pdpj.jus.br/servicos-estruturantes/tpu/)
Classificações de assuntos, classes, movimentos e documentos; contrato e acesso por validar.
A10 — CNJ — Portaria 374/2026
[https://atos.cnj.jus.br/atos/detalhar/6972](https://atos.cnj.jus.br/atos/detalhar/6972)
Restrição expressa à exploração comercial dos dados DataJud.
A11 — CNJ — Portaria 442/2026
[https://atos.cnj.jus.br/atos/detalhar/7057](https://atos.cnj.jus.br/atos/detalhar/7057)
Publicada em 24/09/2026. Requisitos adicionais para entidades privadas no acesso a dados consolidados.
A12 — CNJ — Resolução 574/2024
[https://atos.cnj.jus.br/atos/detalhar/5708](https://atos.cnj.jus.br/atos/detalhar/5708)
Acesso centralizado por instrumento próprio e custeio de infraestrutura; não libera o Jumbi automaticamente.
A13 — CNJ — Resolução 455/2022, compilada
[https://atos.cnj.jus.br/atos/detalhar/4509](https://atos.cnj.jus.br/atos/detalhar/4509)
Referência do estudo v1 para canais, ciência e recibos; conferir vigência na implantação.
A14 — CNJ — integração para tribunais, MNI
[https://www.cnj.jus.br/integracao-para-os-tribunais/](https://www.cnj.jus.br/integracao-para-os-tribunais/)
Referência histórica; não tomar versão antiga como contrato de todas as instâncias.
A15 — TJCE — Portaria 2026/2026, PDTIC
[https://www.tjce.jus.br/atos_normativos/portaria-no-2026-2026/](https://www.tjce.jus.br/atos_normativos/portaria-no-2026-2026/)
Planejamento de interfaces PJe/MNI, não prova de liberação de API externa ao Jumbi.
A16 — PDPJ — consulta de precedentes Pangea/BNP
[https://docs.pdpj.jus.br/servicos-negociais/pangeabnp/](https://docs.pdpj.jus.br/servicos-negociais/pangeabnp/)
Integração autenticada; não confundir documentação institucional com permissão do SaaS.
A17 — OpenAI — instruções de projeto para agentes
[https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)
AGENTS.md enxuto; especificação extensa em arquivo de tarefa separado.
A18 — CNJ — Portaria 316/2024, consolidação
[https://atos.cnj.jus.br/atos/detalhar/5792](https://atos.cnj.jus.br/atos/detalhar/5792)
Referida expressamente pela Portaria 442/2026; texto integral não revalidado nesta revisão.
Limitação técnica observada
As tentativas de baixar YAML e algumas páginas diretamente retornaram bloqueio/erro no navegador de pesquisa; o ambiente de execução não resolveu DNS externo. Assim, nenhum arquivo de contrato judicial foi apresentado como baixado ou homologado. O pacote contém ferramentas para obter e conferir os contratos no ambiente do desenvolvedor. Exemplos de contratos em tests/fixtures são sintéticos.
