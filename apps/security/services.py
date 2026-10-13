"""Account-scoped MFA, encrypted seeds, replay protection and session revocation."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import AccountSecurity, SecurityEvent


def cipher():
    key = hashlib.sha256(('jumbi-mfa-v1:' + settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode()


def totp(secret, counter):
    digest = hmac.new(base64.b32decode(secret), struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = (struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000
    return f'{number:06d}'


def matched_counter(secret, code, last_counter=-1):
    code = str(code).strip().replace(' ', '')
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    now = int(time.time()) // 30
    for counter in (now, now - 1, now + 1):
        if counter > last_counter and counter >= 0 and hmac.compare_digest(totp(secret, counter), code):
            return counter
    return None


def event(user, action):
    SecurityEvent.objects.create(user=user, action=action)


@transaction.atomic
def verify_code(user, code, *, expected_epoch=None):
    profile = AccountSecurity.objects.select_for_update().get(user=user)
    if expected_epoch is not None and profile.session_epoch != expected_epoch:
        return False
    if not profile.enabled or (profile.locked_until and profile.locked_until > timezone.now()):
        return False
    secret = cipher().decrypt(profile.secret_ciphertext.encode()).decode()
    counter = matched_counter(secret, code, profile.last_counter)
    matched_recovery = None
    if counter is None and 10 <= len(code.strip()) <= 64:
        for index, encoded in enumerate(profile.recovery_hashes):
            if check_password(code.strip().upper(), encoded):
                matched_recovery = index
                break
    valid = counter is not None or matched_recovery is not None
    if valid:
        if counter is not None:
            profile.last_counter = counter
        else:
            profile.recovery_hashes.pop(matched_recovery)
            event(user, 'Código de recuperação utilizado')
        profile.failures = 0
        profile.locked_until = None
    else:
        if profile.locked_until and profile.locked_until <= timezone.now():
            profile.failures = 0
        profile.failures += 1
        if profile.failures >= 5:
            profile.locked_until = timezone.now() + timedelta(minutes=15)
    profile.save()
    return valid


def mark_verified(request, profile):
    request.session.cycle_key()
    request.session['security_epoch'] = profile.session_epoch
    request.session['mfa_epoch'] = profile.session_epoch
    request.session.pop('mfa_challenge_started', None)


@transaction.atomic
def enroll(request, secret, code):
    profile, _ = AccountSecurity.objects.select_for_update().get_or_create(user=request.user)
    if profile.session_epoch != request.session.get('security_epoch', 0):
        raise PermissionDenied('Esta sessão foi encerrada. Entre novamente.')
    if profile.enabled:
        return None
    counter = matched_counter(secret, code)
    if counter is None:
        return None
    codes = [secrets.token_hex(8).upper() for _ in range(8)]
    profile.secret_ciphertext = cipher().encrypt(secret.encode()).decode()
    profile.enabled = True
    profile.last_counter = counter
    profile.recovery_hashes = [make_password(code) for code in codes]
    profile.session_epoch += 1
    profile.failures = 0
    profile.locked_until = None
    profile.save()
    mark_verified(request, profile)
    event(request.user, 'Autenticação em duas etapas ativada')
    return codes


@transaction.atomic
def revoke_other_sessions(request, *, disable=False):
    profile, _ = AccountSecurity.objects.select_for_update().get_or_create(user=request.user)
    if profile.session_epoch != request.session.get('security_epoch', 0):
        raise PermissionDenied('Esta sessão foi encerrada. Entre novamente.')
    profile.session_epoch += 1
    if disable:
        profile.enabled = False
        profile.secret_ciphertext = ''
        profile.recovery_hashes = []
        profile.last_counter = -1
    profile.save()
    mark_verified(request, profile)
    event(request.user, 'Autenticação em duas etapas desativada' if disable else 'Outras sessões encerradas')


@transaction.atomic
def verify_current_password(user, password):
    profile, _ = AccountSecurity.objects.select_for_update().get_or_create(user=user)
    now = timezone.now()
    if profile.password_locked_until and profile.password_locked_until > now:
        return False
    if profile.password_locked_until:
        profile.password_failures = 0
        profile.password_locked_until = None
    valid = user.check_password(password)
    profile.password_failures = 0 if valid else profile.password_failures + 1
    if profile.password_failures >= 5:
        profile.password_locked_until = now + timedelta(minutes=15)
    profile.save(update_fields=['password_failures', 'password_locked_until'])
    return valid
