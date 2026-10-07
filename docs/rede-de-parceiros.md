# Rede de Parceiros Jumbi

## Objetivo

A Rede de Parceiros é um CRM de relacionamento vinculado a cada escritório. Ela recebe oportunidades, organiza a triagem, registra a origem e permite a conversão controlada em cliente e caso jurídico.

O parceiro usa um portal externo. Ele não recebe `Membership` da organização e não acessa clientes, processos, documentos, financeiro, equipe ou configurações internas.

## Decisão de produto

O nome de produto é **Rede de Parceiros**, não “Programa de Afiliados”.

A primeira versão não calcula comissão por indicação, percentual sobre honorários, saldo ou saque. Uma organização pode documentar uma política financeira contratual, mas o sistema exige:

- confirmação de conformidade pelo escritório;
- descrição da base contratual;
- aprovação e operação externas ao cálculo de honorários;
- ausência de automação ligada à conversão de clientes.

Essa separação reduz o risco de a infraestrutura ser usada como mecanismo de captação ou mercantilização. A política do escritório deve observar, entre outras normas aplicáveis, o [Provimento OAB 205/2021](https://www.oab.org.br/leisnormas/legislacao/provimentos/205-2021) e o [Código de Ética e Disciplina](https://www.oab.org.br/leisnormas/legislacao/resolucoes/02-2015).

## Papéis e isolamento

### Direção e gerência

- habilitam ou suspendem a rede;
- confirmam a revisão de conformidade;
- criam categorias, parceiros, campanhas e materiais;
- aprovam, suspendem ou bloqueiam parceiros;
- acompanham indicadores;
- atualizam o funil;
- convertem uma oportunidade em cliente e caso;
- consultam registros de auditoria.

### Operação

- acessa o módulo interno;
- qualifica e atualiza oportunidades;
- converte oportunidades autorizadas em cliente e caso;
- não altera governança, parceiros, campanhas ou materiais.

### Consulta

- não acessa a Rede de Parceiros, porque ela contém dados pessoais e informações de origem comercial.

### Parceiro

- entra pelo login único do Jumbi;
- é direcionado para `/parceiros/`;
- aceita os termos e o aviso de privacidade no primeiro acesso;
- registra oportunidades com consentimento;
- vê apenas suas próprias oportunidades;
- recebe somente status simplificado e mensagens autorizadas;
- atualiza os próprios dados de contato;
- consulta campanhas e materiais permitidos.

## Fluxo

1. O escritório configura e habilita a rede.
2. A direção cria o parceiro com e-mail exclusivo.
3. O parceiro é aprovado manualmente.
4. No primeiro acesso, o parceiro aceita regras e aviso de privacidade.
5. O parceiro registra uma oportunidade com contato, contexto e consentimento.
6. O Jumbi verifica documento protegido, e-mail, telefone e nome para indicar possíveis duplicidades.
7. A equipe interna move a oportunidade pelo funil.
8. Cada transição gera evento e `AuditLog`.
9. Quando qualificada, a oportunidade pode criar um `Client` e um `LegalCase`.
10. O parceiro continua vendo somente o resumo público.

## Funil interno

- Nova
- Em análise
- Contato realizado
- Documentos pendentes
- Aguardando retorno
- Consulta agendada
- Proposta enviada
- Contrato em formalização
- Convertida
- Caso criado
- Cancelada
- Não convertida
- Possível duplicidade

No portal, essas etapas são agrupadas em:

- Recebida pelo escritório
- Em atendimento
- Em formalização
- Convertida
- Encerrada

## Proteção de dados

- O documento informado não é armazenado em texto puro. O sistema guarda apenas uma versão mascarada e um HMAC para comparação de duplicidade.
- Consentimento, versão do aviso, data, hora e IP são registrados na oportunidade.
- Notas internas e eventos internos nunca são renderizados no portal.
- Consultas internas e externas sempre são filtradas pela organização e pelo parceiro autenticado.
- Campanhas respeitam datas, categoria e limites total/por parceiro.
- Parceiros bloqueados, rejeitados ou desativados não conseguem autenticar no portal.

## Modelos

- `PartnerNetworkSettings`: ativação, apresentação, critérios, privacidade e governança.
- `PartnerCategory`: classificação livre por organização.
- `Partner`: identidade, acesso, categoria, status e aceite.
- `PartnerCampaign`: área jurídica, período, elegibilidade, limites e critérios.
- `PartnerOpportunity`: origem, contato, consentimento, funil e conversão.
- `PartnerOpportunityEvent`: histórico público/interno de transições.
- `PartnerMaterial`: guias, políticas, treinamentos e links autorizados.

## Rotas

- Gestão interna: `/juridico/modulo/partners/`
- Portal externo: `/parceiros/`
- Login único: `/entrar/`

## Testes

O conjunto automatizado cobre:

- roteamento do login;
- ausência de membership interno;
- bloqueio de parceiro;
- autorização por papel;
- isolamento entre organizações;
- isolamento entre parceiros;
- ausência de notas internas no portal;
- consentimento;
- detecção de duplicidade;
- transição auditada;
- conversão em cliente e caso;
- ausência de campos de comissão automática.
