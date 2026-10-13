# Mapa de clientes

O mapa nacional reúne os cadastros que a pessoa autenticada está autorizada a consultar e agrupa cada um pelo estado informado em sua ficha. A distribuição é estadual: não representa o endereço exato, a localização atual ou a posição de cada cliente.

## Como usar

1. Abra **Mapa de clientes**, na seção **Acervo** do menu, logo após **Pessoas**.
2. Escolha o alcance: **Todos os cadastros** ou **Clientes com pasta acessível**. O segundo considera somente pessoas vinculadas a pastas que o usuário pode consultar.
3. Se necessário, filtre o tipo de pessoa e busque por nome, nome fantasia ou cidade. Clique em **Aplicar filtros**.
4. Selecione uma UF no mapa, no ranking ou na lista de estados. A página abre a lista correspondente. **Limpar estado** remove somente essa seleção e mantém os demais filtros.
5. Use **Abrir ficha** para consultar a pessoa. Em registros sem estado ou com um estado não reconhecido, os usuários que podem editar recebem também **Completar endereço**.

Os totais, a escala e o ranking representam o alcance, o tipo e a busca ativos. Selecionar uma UF filtra apenas a lista de pessoas; os números nacionais permanecem disponíveis para comparação. Cada pessoa é contada uma vez, mesmo quando possui várias pastas. O percentual do ranking usa como base os cadastros localizados no Brasil, sem incluir registros pendentes ou fora do país.

**Todos os cadastros** inclui pessoas e empresas da base autorizada, inclusive cadastros inativos; não significa somente clientes com processos. Filtros inválidos exibem um erro em vez de ampliar a consulta silenciosamente.

## Endereços e privacidade

- Siglas de UF e nomes completos de estados brasileiros são reconhecidos, incluindo o Distrito Federal, independentemente de acentos e maiúsculas.
- País vazio, Brasil, Brazil, BR ou BRA são tratados como Brasil. Outros países aparecem separadamente em **Fora do Brasil**.
- **Estado não informado** e **Estado não reconhecido** são situações distintas. A aplicação não tenta deduzir a UF pela cidade, pelo CEP ou por um serviço externo.
- As mesmas regras de organização, perfil e acesso a pastas continuam valendo. O mapa não concede acesso adicional a fichas.
- As formas geográficas são arquivos públicos locais. A aplicação não envia nomes, endereços, buscas, contagens ou outros dados do escritório ao IBGE ou a qualquer serviço de mapas.
- A página funciona sem JavaScript: todos os estados são links nativos e a lista de 27 UFs oferece navegação por teclado e alternativa textual ao desenho. O JavaScript somente mostra o nome e a contagem do estado ao passar o ponteiro ou focar o link.

## Fonte geográfica

**Fonte: Instituto Brasileiro de Geografia e Estatística — IBGE.** As 27 geometrias foram obtidas em 13/10/2026 pela [API de malhas territoriais, versão 3](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3), em resolução de unidades da federação e qualidade mínima. São malhas simplificadas para apresentação visual, sem finalidade cadastral ou de demarcação.

Consulta original: [GeoJSON do Brasil dividido em UFs](https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo%2Bjson&intrarregiao=UF&qualidade=minima).

Nomes e códigos conferidos com o [serviço oficial de localidades do IBGE](https://servicodados.ibge.gov.br/api/v1/localidades/estados?orderBy=nome). Há exatamente 27 códigos de UF, todos correspondentes às geometrias. O [acervo de malhas territoriais](https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/) identifica os arquivos disponibilizados como públicos. A resposta utilizada não fornece uma licença SPDX específica; por isso não se atribui aqui uma licença não informada pela fonte. A atribuição ao IBGE é preservada no mapa e nos metadados do SVG.

Arquivos versionados:

- `static/maps/brazil-states.geojson`: resposta pública original, após descompressão HTTP. SHA-256: `07c671aa87aa1ab296c446de6294df9827112782537b996c0a160284907e7c0f`.
- `static/maps/brazil-states.svg`: derivação local com os polígonos de cada UF, sem scripts ou referências remotas. Os anéis internos das geometrias são preservados com `fill-rule="evenodd"`.

A transformação utiliza longitude ajustada pelo cosseno da latitude central e latitude invertida, com enquadramento em 900 × 860 unidades e coordenadas arredondadas a duas casas. Os rótulos das UFs usam pontos interiores dos polígonos; eles não indicam capitais ou clientes. O rótulo do Distrito Federal é deslocado com uma linha de chamada para facilitar a leitura.

A API consultada não informa uma data de edição da malha na resposta; a data acima é a da obtenção. Em uma futura atualização, conferir novamente os 27 códigos, preservar a atribuição, registrar a nova origem e o hash, e verificar visualmente os dois temas e as telas móveis antes da publicação.
