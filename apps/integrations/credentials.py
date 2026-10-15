import base64
import hashlib
import json
from cryptography.fernet import Fernet
from django.conf import settings

PREFIX = "fernet:v1:"


def cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("jumbi-integrations-v1:" + settings.SECRET_KEY).encode()).digest()))


def encrypt_credentials(value):
    if not value:
        return ""
    return PREFIX + cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


def decrypt_credentials(value):
    if not value:
        return {}
    if not value.startswith(PREFIX):
        raise ValueError("Credencial legada precisa ser protegida antes do uso.")
    return json.loads(cipher().decrypt(value[len(PREFIX):].encode()))
