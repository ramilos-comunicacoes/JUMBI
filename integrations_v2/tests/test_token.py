import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.parse import parse_qs
from examples.pdpj_token import obtain_token, ServiceToken, TokenError


class TokenTests(unittest.TestCase):
    def opener_for(self, data):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.read.return_value = json.dumps(data).encode()
        return opener

    def test_valid_token(self):
        opener = self.opener_for({'access_token': 'SYNTHETIC_LOCAL_ONLY', 'token_type': 'Bearer', 'expires_in': 60})
        with patch('examples.pdpj_token.make_opener', return_value=opener):
            token = obtain_token('sandbox', 'synthetic-client', 'synthetic-secret')
        self.assertEqual(token.expires_in, 60)
        self.assertNotIn('SYNTHETIC_LOCAL_ONLY', repr(token))
        request = opener.open.call_args.args[0]
        fields = parse_qs(request.data.decode())
        self.assertEqual(fields['grant_type'], ['client_credentials'])
        self.assertEqual(request.method, 'POST')
        self.assertIn('sso.stg.cloud.pje.jus.br', request.full_url)

    def test_missing_creds_no_network(self):
        with patch('examples.pdpj_token.make_opener') as opener:
            with self.assertRaises(TokenError):
                obtain_token('sandbox', '', '')
            opener.assert_not_called()

    def test_invalid_environment(self):
        with self.assertRaises(TokenError):
            obtain_token('arbitrary', 'client', 'secret')

    def test_invalid_response_types(self):
        for data in (
            [],
            {},
            {'access_token': 'x', 'token_type': None, 'expires_in': 10},
            {'access_token': 'x', 'token_type': 'Bearer', 'expires_in': True},
            {'access_token': 'x', 'token_type': 'Bearer', 'expires_in': 0},
            {'access_token': '', 'token_type': 'Bearer', 'expires_in': 60},
        ):
            with self.subTest(data=data):
                with patch('examples.pdpj_token.make_opener', return_value=self.opener_for(data)):
                    with self.assertRaises(TokenError):
                        obtain_token('sandbox', 'x', 'y')

    def test_error_does_not_leak_secret(self):
        with patch('examples.pdpj_token.make_opener', side_effect=RuntimeError('very-secret-value')):
            with self.assertRaises(TokenError) as result:
                obtain_token('sandbox', 'x', 'y')
            self.assertNotIn('very-secret-value', str(result.exception))

    def test_oversized_response(self):
        opener = self.opener_for({})
        opener.open.return_value.__enter__.return_value.read.return_value = b'x' * (1024 * 1024 + 1)
        with patch('examples.pdpj_token.make_opener', return_value=opener):
            with self.assertRaises(TokenError):
                obtain_token('sandbox', 'x', 'y')
