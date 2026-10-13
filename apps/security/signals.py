from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from .models import AccountSecurity


@receiver(user_logged_in, dispatch_uid='jumbi_security_login')
def record_login_epoch(sender, request, user, **kwargs):
    profile = AccountSecurity.objects.filter(user=user).first()
    request.session['security_epoch'] = profile.session_epoch if profile else 0
    request.session.pop('mfa_epoch', None)
    request.session.pop('mfa_challenge_started', None)
