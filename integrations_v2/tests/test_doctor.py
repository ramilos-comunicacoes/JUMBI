import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock
from tools.doctor_integrations import main, fetch_target, NoRedirect, atomic_private_write


class DoctorTests(unittest.TestCase):
    def make_response(self, body, content_type='application/json'):
        opener = MagicMock()
        r = opener.open.return_value.__enter__.return_value
        r.read.return_value = body
        r.status = 200
        r.headers = {'Content-Type': content_type}
        return opener

    def test_dry_run_zero_network(self):
        with patch('sys.argv', ['doctor', '--target', 'djen-tribunais']), patch('sys.stdout', new_callable=io.StringIO) as output, patch('tools.doctor_integrations.make_opener') as opener:
            self.assertEqual(main(), 0)
            opener.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['request_count'], 0)

    def test_redirect_refused(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid/'))

    def test_fetch_mock_and_private_write(self):
        with tempfile.TemporaryDirectory() as d, patch('tools.doctor_integrations.make_opener', return_value=self.make_response(b'{"synthetic":true}')) as maker:
            result = fetch_target('djen-tribunais', Path(d))
            self.assertTrue(result['saved'])
            self.assertEqual(result['status'], 'fetched_NOT_homologated')
            self.assertEqual(Path(result['file']).read_bytes(), b'{"synthetic":true}')
            maker.return_value.open.assert_called_once()

    def test_html_and_empty_not_saved(self):
        for body, ct in ((b'<html>403</html>', 'text/html'), (b'', 'application/json'), (b' <!DOCTYPE html><html/>', 'application/json')):
            with tempfile.TemporaryDirectory() as d, patch('tools.doctor_integrations.make_opener', return_value=self.make_response(body, ct)):
                result = fetch_target('djen-tribunais', Path(d))
                self.assertFalse(result['saved'])

    def test_rate_limit_explicit(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError('https://example.invalid', 429, 'limit', {'Retry-After': '60'}, None)
        with tempfile.TemporaryDirectory() as d, patch('tools.doctor_integrations.make_opener', return_value=opener):
            result = fetch_target('djen-tribunais', Path(d))
            self.assertEqual(result['http_status'], 429)
            self.assertEqual(result['retry_after'], '60')
            self.assertFalse(result['saved'])

    def test_network_failure_not_empty(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError('synthetic')
        with tempfile.TemporaryDirectory() as d, patch('tools.doctor_integrations.make_opener', return_value=opener):
            result = fetch_target('djen-tribunais', Path(d))
            self.assertEqual(result['status'], 'network_error')
            self.assertFalse(result['saved'])

    def test_write_is_atomic_and_private(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'contract'
            atomic_private_write(p, b'one')
            atomic_private_write(p, b'two')
            self.assertEqual(p.read_bytes(), b'two')
            if os.name == 'posix':
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
