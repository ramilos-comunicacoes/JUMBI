import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from datetime import timedelta

from apps.core.models import Membership, Organization
from .models import AccountSecurity
from .services import cipher, new_secret, totp, verify_code


@override_settings(JUMBI_ENFORCE_SUBSCRIPTIONS=False)
class SecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email='security@example.test', password='Account-test-password9')
        cls.org = Organization.objects.create(name='Security', slug='security', business_type='office')
        Membership.objects.create(organization=cls.org, user=cls.user, role='owner')

    def setUp(self):
        self.client.force_login(self.user)

    def enable(self):
        self.client.post('/seguranca/conta/', {'action': 'begin', 'password': 'Account-test-password9'})
        pending = self.client.session['mfa_setup']
        secret = cipher().decrypt(pending['secret'].encode()).decode()
        response = self.client.post('/seguranca/conta/', {'action': 'enable', 'code': totp(secret, int(time.time()) // 30)})
        self.assertEqual(response.status_code, 200)
        return secret, response

    def test_known_totp_vector(self):
        # RFC 6238 SHA-1 vector at t=59, truncated to six digits.
        self.assertEqual(totp('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', 1), '287082')

    def test_enrollment_ciphertext_and_single_display_recovery(self):
        secret, response = self.enable()
        profile = AccountSecurity.objects.get(user=self.user)
        self.assertTrue(profile.enabled)
        self.assertNotIn(secret, profile.secret_ciphertext)
        codes = response.context['recovery_codes']
        self.assertEqual(len(codes), 8)
        self.assertNotIn(codes[0], str(profile.recovery_hashes))
        self.assertIsNone(self.client.get('/seguranca/conta/').context['recovery_codes'])
        self.assertFalse(verify_code(self.user, totp(secret, profile.last_counter)))
        self.assertTrue(verify_code(self.user, codes[0]))
        self.assertFalse(verify_code(self.user, codes[0]))

    def test_new_login_cannot_bypass_challenge_via_dashboard_or_admin(self):
        secret, response = self.enable()
        recovery = response.context['recovery_codes'][0]
        other = Client()
        self.assertTrue(other.login(username=self.user.email, password='Account-test-password9'))
        for url in ['/juridico/', '/admin/', '/auditoria/', '/seguranca/senha/']:
            self.assertRedirects(other.get(url), '/seguranca/conta/confirmar/?next=' + url.replace('/', '%2F'), fetch_redirect_response=False)
        response = other.post('/seguranca/conta/confirmar/', {'code': recovery, 'next': 'https://evil.example/'})
        self.assertEqual(response.url, '/juridico/')
        self.assertEqual(other.get('/juridico/').status_code, 200)

    def test_invalid_codes_lock_for_fifteen_minutes(self):
        self.enable()
        for _ in range(5):
            self.assertFalse(verify_code(self.user, 'invalid'))
        profile = AccountSecurity.objects.get(user=self.user)
        self.assertGreater(profile.locked_until, timezone.now())
        AccountSecurity.objects.filter(user=self.user).update(locked_until=timezone.now() - timedelta(seconds=1))
        self.assertFalse(verify_code(self.user, 'invalid'))
        profile.refresh_from_db()
        self.assertEqual(profile.failures, 1)

    def test_revoke_others_keeps_current_session(self):
        other = Client()
        other.force_login(self.user)
        self.client.post('/seguranca/conta/', {'action': 'revoke', 'password': 'Account-test-password9'})
        self.assertEqual(self.client.get('/juridico/').status_code, 200)
        self.assertRedirects(other.get('/juridico/'), '/entrar/', fetch_redirect_response=False)

    def test_revoke_requires_password(self):
        response = self.client.post('/seguranca/conta/', {'action': 'revoke', 'password': 'wrong'})
        self.assertContains(response, 'Senha inválida')
        self.assertEqual(AccountSecurity.objects.get(user=self.user).password_failures, 1)

    def test_disable_requires_password_and_fresh_code(self):
        secret, response = self.enable()
        code = response.context['recovery_codes'][0]
        self.client.post('/seguranca/conta/', {'action': 'disable', 'password': 'wrong', 'code': code})
        self.assertTrue(AccountSecurity.objects.get(user=self.user).enabled)
        self.client.post('/seguranca/conta/', {'action': 'disable', 'password': 'Account-test-password9', 'code': code})
        profile = AccountSecurity.objects.get(user=self.user)
        self.assertFalse(profile.enabled)
        self.assertEqual(profile.secret_ciphertext, '')
        self.assertEqual(profile.recovery_hashes, [])

    def test_client_role_cannot_open_internal_data(self):
        Membership.objects.filter(user=self.user).update(role='client')
        for url in ['/juridico/contacts/', '/auditoria/', '/equipe/', '/admin/']:
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_challenge_expires(self):
        self.enable()
        other = Client()
        other.force_login(self.user)
        session = other.session
        session['mfa_challenge_started'] = time.time() - 601
        session.save()
        self.assertRedirects(other.get('/seguranca/conta/confirmar/'), '/entrar/', fetch_redirect_response=False)

    def test_revocation_during_mfa_verification_cannot_adopt_new_epoch(self):
        _, response = self.enable()
        recovery = response.context['recovery_codes'][0]
        other = Client()
        other.force_login(self.user)
        from .services import verify_code as original_verify
        def verify_and_revoke(*args, **kwargs):
            result = original_verify(*args, **kwargs)
            profile = AccountSecurity.objects.get(user=self.user)
            profile.session_epoch += 1
            profile.save(update_fields=['session_epoch'])
            return result
        with patch('apps.security.views.verify_code', side_effect=verify_and_revoke):
            other.post('/seguranca/conta/confirmar/', {'code': recovery})
        self.assertRedirects(other.get('/juridico/'), '/entrar/', fetch_redirect_response=False)

    def test_second_factor_rejects_stale_epoch(self):
        _, response = self.enable()
        profile = AccountSecurity.objects.get(user=self.user)
        self.assertFalse(verify_code(self.user, response.context['recovery_codes'][0], expected_epoch=profile.session_epoch - 1))
