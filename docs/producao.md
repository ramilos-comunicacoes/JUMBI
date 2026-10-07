# Publicacao na VPS

O prototipo local usa SQLite apenas para demonstracao. A VPS deve usar PostgreSQL e uma credencial nova de administrador.

## Itens necessarios

1. Servidor Linux atualizado, dominio e acesso SSH por chave.
2. PostgreSQL com banco e usuario exclusivos do Djumbi.
3. Variaveis de ambiente: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` e as variaveis `POSTGRES_*`.
4. Nginx como proxy HTTPS, Gunicorn para Django e certificado TLS com renovacao automatica.
5. Backup diario do PostgreSQL e monitoramento de erros/logs.

## Primeiro deploy

Depois de configurar as variaveis no servidor:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

Nunca reutilize a senha do ambiente local e nunca envie o arquivo `.env` ao GitHub.
