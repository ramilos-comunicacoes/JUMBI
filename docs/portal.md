# Revisão de documentos e portal do cliente

O módulo reutiliza os documentos privados e suas versões imutáveis. Não duplica arquivos nem oferece URLs públicas.

## Operação

1. Direção/gestão convida uma pessoa em **Equipe** com perfil **Cliente · somente portal**. Ela aceita o convite e define a própria senha.
2. Em **Revisão e portal → Vincular cliente**, a gestão confere a identidade e associa explicitamente a conta a um contato de uma pasta acessível. Igualdade de e-mail, telefone ou nome nunca concede acesso.
3. A equipe solicita revisão de uma **versão exata** a uma pessoa da direção/gestão, diferente de quem solicitou e de quem enviou o arquivo. A revisora deve ter acesso atual à pasta.
4. A pessoa designada baixa o arquivo, registra aprovação ou ajustes e uma justificativa. A decisão fica vinculada ao número da versão e ao SHA-256, com histórico imutável.
5. A gestão publica a versão aprovada para um vínculo específico. Título e mensagem de apresentação são escolhidos explicitamente; dados internos da pasta e observações de revisão não aparecem no portal.
6. O cliente autenticado pode baixar as versões publicadas e conversar sobre cada documento. Novas versões não substituem silenciosamente publicações anteriores.

## Permissões, planos e preservação

- Solicitar revisão: direção, gestão e operação; decidir: apenas pessoa designada, direção/gestão; vincular e publicar: direção/gestão. Consulta não gerencia o portal.
- Novos vínculos, revisões, decisões, publicações e mensagens exigem **Max ativo**. Consulta de publicações existentes e download permanecem disponíveis após expiração/downgrade, sujeitos às permissões. Revogação pela direção/gestão continua disponível.
- Perfil Cliente tem acesso somente ao portal. Não concede acesso aos módulos internos, outras pessoas, pastas, minutas ou arquivos não publicados.
- Em pastas sigilosas, o cliente também precisa constar explicitamente em **Pessoas autorizadas** da pasta. Publicar não adiciona essa permissão implicitamente. Remover a autorização, trocar o cliente da pasta, desativar membro/conta, revogar vínculo ou publicação corta o acesso.
- Revogar um vínculo retira suas publicações; revogar uma publicação retira só aquela versão. Revogação não apaga decisões, mensagens ou arquivos e não pode ser revertida silenciosamente.
- Downloads verificam o hash dos bytes antes de retornar o arquivo, usam attachment, no-store e nosniff. Não há cache offline de documentos, bearer links ou envio automático externo.
- Mensagens são texto escapado e ficam restritas ao destinatário da publicação e à equipe com acesso à pasta. As telas paginam documentos, revisões e mensagens. Gestão mostra os 30 vínculos/publicações mais recentes.
- Aprovação interna **não é assinatura eletrônica** e não altera o estado jurídico do documento.
- Exportação interna usa `scoped_portal_queryset(actor, organization, model)` para preservar acesso por pasta e histórico, sem depender do plano. Contas Cliente não recebem exportação dos registros internos; podem baixar seus arquivos publicados.

## Validação

Testes exercitam revisão independente, versão exata, rejeição, imutabilidade, hash dos bytes, cliente errado, outro escritório, sigilo atual, revogação, desativação, mudança do cliente da pasta, mensagens escapadas, CSRF, formulários, limites de plano e preservação pós-expiração.
