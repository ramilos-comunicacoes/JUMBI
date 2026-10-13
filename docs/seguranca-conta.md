# Segurança da conta

A tela `/seguranca/conta/` permite configurar autenticação TOTP de seis dígitos por aplicativo, trocar a senha e encerrar outras sessões. Está disponível em ambos os planos, inclusive para o perfil Cliente.

A ativação exige senha atual e confirmação do primeiro código. A chave de configuração expira em dez minutos e fica cifrada na sessão de servidor. O segredo permanente usa Fernet com chave derivada da `DJANGO_SECRET_KEY`; os oito códigos de recuperação são armazenados como hashes e exibidos uma única vez. Cada código de recuperação funciona apenas uma vez. Os códigos TOTP aceitos não podem ser reutilizados, incluindo o código usado na configuração. Existe tolerância de um intervalo de trinta segundos para diferença de relógio.

Cinco erros de segunda etapa bloqueiam a verificação por quinze minutos. A confirmação de senha para ações sensíveis tem contador separado e persistido, com o mesmo intervalo. Alterações usam bloqueio transacional. A segunda etapa cobre todas as rotas autenticadas, inclusive Django Admin e portal; uma sessão com senha verificada tem dez minutos para concluí-la. Revogação de sessões incrementa uma geração de segurança; outras sessões encerram no próximo pedido, sem impedir um novo login legítimo. A geração não pode ser atualizada implicitamente por uma verificação concorrente de código.

As contas existentes continuam acessíveis com as credenciais anteriores até o titular configurar o próprio autenticador. A publicação não cadastra dispositivos em nome do titular nem ativa MFA silenciosamente.

A chave secreta do ambiente e o banco devem permanecer no backup administrativo privado. Rotacionar `DJANGO_SECRET_KEY` exige um procedimento de recriptografia dos segredos antes da troca; não altere a chave sem planejamento. Perda simultânea do autenticador e dos códigos requer atendimento administrativo com verificação de identidade; não existe recuperação automática por e-mail nesta versão. Segredos MFA e eventos pessoais de segurança não integram a exportação dos dados de um escritório.
