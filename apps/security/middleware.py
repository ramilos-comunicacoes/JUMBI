import time

from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from .models import AccountSecurity


class AccountSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.user.is_authenticated:
            return None
        profile = AccountSecurity.objects.filter(user=request.user).first()
        if not profile:
            return None
        epoch = request.session.get('security_epoch', 0)
        if epoch != profile.session_epoch:
            logout(request)
            return redirect('core:login')
        if not profile.enabled or request.session.get('mfa_epoch') == profile.session_epoch:
            return None
        started = request.session.setdefault('mfa_challenge_started', time.time())
        if time.time() - started > 600:
            logout(request)
            return redirect('core:login')
        match = request.resolver_match
        if match and match.view_name in {'security:challenge', 'core:logout'}:
            return None
        target = request.get_full_path() if request.method in {'GET', 'HEAD'} else reverse('legal:dashboard')
        return redirect(reverse('security:challenge') + '?' + urlencode({'next': target}))
