import time

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .models import AccountSecurity, SecurityEvent
from .services import cipher, enroll, event, mark_verified, new_secret, revoke_other_sessions, verify_code, verify_current_password


class CodeForm(forms.Form):
    code = forms.CharField(label='Código do autenticador ou de recuperação', max_length=64,
                           widget=forms.TextInput(attrs={'autocomplete': 'one-time-code', 'autofocus': True}))


class PasswordForm(forms.Form):
    password = forms.CharField(label='Senha atual', widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))


class DisableForm(PasswordForm):
    code = forms.CharField(label='Código do autenticador ou de recuperação', max_length=64)


def password_valid(request, form):
    if not verify_current_password(request.user, form.cleaned_data['password']):
        form.add_error('password', 'Senha inválida ou limite de tentativas atingido. Após cinco tentativas, aguarde 15 minutos.')
        return False
    return True


@sensitive_post_parameters('code')
@login_required
@require_http_methods(['GET', 'POST'])
def challenge(request):
    profile = AccountSecurity.objects.filter(user=request.user).first()
    destination = request.POST.get('next', request.GET.get('next', ''))
    if not url_has_allowed_host_and_scheme(destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        destination = reverse('core:platform' if request.user.is_superuser else 'legal:dashboard')
    if not profile or not profile.enabled or request.session.get('mfa_epoch') == profile.session_epoch:
        return redirect(destination)
    form = CodeForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        if verify_code(request.user, form.cleaned_data['code'], expected_epoch=profile.session_epoch):
            mark_verified(request, profile)
            event(request.user, 'Acesso confirmado com segunda etapa')
            return redirect(destination)
        form.add_error('code', 'Código inválido, já utilizado ou bloqueado. Após cinco tentativas, aguarde 15 minutos.')
    return render(request, 'security/challenge.html', {'form': form, 'next': destination})


@sensitive_post_parameters('password', 'code')
@login_required
@require_http_methods(['GET', 'POST'])
def account(request):
    profile = AccountSecurity.objects.filter(user=request.user).first()
    enabled = bool(profile and profile.enabled)
    form = PasswordForm(auto_id='setup_%s')
    revoke_form = PasswordForm(auto_id='revoke_%s')
    disable_form = DisableForm(auto_id='disable_%s')
    code_form = CodeForm()
    codes = None
    pending = request.session.get('mfa_setup')
    if pending and time.time() - pending['at'] > 600:
        request.session.pop('mfa_setup', None)
        pending = None
    action = request.POST.get('action')
    if request.method == 'POST':
        if action in {'begin', 'revoke'}:
            active_form = PasswordForm(request.POST, auto_id=('setup_%s' if action == 'begin' else 'revoke_%s'))
            if action == 'begin':
                form = active_form
            else:
                revoke_form = active_form
            if active_form.is_valid() and password_valid(request, active_form):
                if action == 'begin' and not enabled:
                    pending = {'secret': cipher().encrypt(new_secret().encode()).decode(), 'at': time.time()}
                    request.session['mfa_setup'] = pending
                elif action == 'revoke':
                    revoke_other_sessions(request)
                    messages.success(request, 'As outras sessões serão encerradas no próximo acesso.')
                    return redirect('security:account')
        elif action == 'enable' and pending and not enabled:
            code_form = CodeForm(request.POST)
            if code_form.is_valid():
                secret = cipher().decrypt(pending['secret'].encode()).decode()
                codes = enroll(request, secret, code_form.cleaned_data['code'])
                if codes:
                    request.session.pop('mfa_setup', None)
                    pending = None
                    enabled = True
                else:
                    code_form.add_error('code', 'Confira o código de seis dígitos do autenticador.')
        elif action == 'disable' and enabled:
            disable_form = DisableForm(request.POST, auto_id='disable_%s')
            if disable_form.is_valid() and password_valid(request, disable_form):
                if verify_code(request.user, disable_form.cleaned_data['code'], expected_epoch=profile.session_epoch):
                    revoke_other_sessions(request, disable=True)
                    messages.success(request, 'Segunda etapa desativada e outras sessões encerradas.')
                    return redirect('security:account')
                disable_form.add_error('code', 'Código inválido, já utilizado ou temporariamente bloqueado.')
    setup_secret = cipher().decrypt(pending['secret'].encode()).decode() if pending and not enabled else ''
    response = render(request, 'security/account.html', {
        'page_title': 'Segurança da conta', 'active_nav': 'security', 'enabled': enabled,
        'form': form, 'revoke_form': revoke_form, 'disable_form': disable_form, 'code_form': code_form,
        'setup_secret': setup_secret, 'recovery_codes': codes,
        'events': SecurityEvent.objects.filter(user=request.user)[:10],
    })
    response['Cache-Control'] = 'private, no-store'
    return response
