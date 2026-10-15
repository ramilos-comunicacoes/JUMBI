import hashlib
import hmac
import unittest
from tools.security_primitives import (
    verify_pdpj_signature,
    validate_allowed_url,
    canonical_request_hash,
    check_reused_key,
    IntegrationInputError,
)


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.body = b'{"notificacaoId":"SYNTHETIC_LOCAL_ONLY","n":1}'
        self.secret = b'synthetic-test-key'
        self.signature = hmac.new(self.secret, self.body, hashlib.sha256).hexdigest()

    def test_valid_signature(self):
        self.assertTrue(verify_pdpj_signature(self.body, self.signature, self.secret))

    def test_uppercase_signature(self):
        self.assertTrue(verify_pdpj_signature(self.body, self.signature.upper(), self.secret))

    def test_original_bytes_required(self):
        self.assertFalse(verify_pdpj_signature(self.body + b' ', self.signature, self.secret))

    def test_wrong_secret(self):
        self.assertFalse(verify_pdpj_signature(self.body, self.signature, b'other'))

    def test_no_secret(self):
        self.assertFalse(verify_pdpj_signature(self.body, self.signature, b''))

    def test_malformed_signatures(self):
        for value in (None, '', 'g' * 64, 'sha256=' + self.signature, self.signature + ' ', 12):
            with self.subTest(value=value):
                self.assertFalse(verify_pdpj_signature(self.body, value, self.secret))

    def test_signature_type_guards(self):
        self.assertFalse(verify_pdpj_signature('text', self.signature, self.secret))
        self.assertFalse(verify_pdpj_signature(self.body, self.signature, 'secret'))

    def test_allowed_url(self):
        self.assertEqual(validate_allowed_url('https://api.example.invalid/v1', {'api.example.invalid'}), 'https://api.example.invalid/v1')

    def test_forbidden_urls(self):
        for value in (
            'http://api.example.invalid/v1',
            'https://api.example.invalid.evil.invalid/v1',
            'https://user:pass@api.example.invalid/v1',
            'https://api.example.invalid:444/v1',
            'https://api.example.invalid/#fragment',
            'https://127.0.0.1/',
            'https://api.example.invalid/\\evil',
            'https://api.example.invalid/ a',
            'https://api.example.invalid:wrong',
        ):
            with self.subTest(url=value):
                with self.assertRaises(IntegrationInputError):
                    validate_allowed_url(value, {'api.example.invalid'})

    def test_internal_hash_stable_key_order(self):
        self.assertEqual(canonical_request_hash({'b': 2, 'a': 1}), canonical_request_hash({'a': 1, 'b': 2}))

    def test_internal_hash_distinguishes_content(self):
        self.assertNotEqual(canonical_request_hash({'n': 1}), canonical_request_hash({'n': 2}))

    def test_non_json_input_rejected(self):
        for value in ({'x': float('nan')}, {'x': object()}):
            with self.assertRaises(IntegrationInputError):
                canonical_request_hash(value)

    def test_same_idempotency_key_and_body(self):
        check_reused_key(canonical_request_hash({'x': 1}), {'x': 1})

    def test_same_key_changed_body(self):
        with self.assertRaisesRegex(IntegrationInputError, 'IDEMPOTENCY_CONFLICT'):
            check_reused_key(canonical_request_hash({'x': 1}), {'x': 2})
