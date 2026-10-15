import json
import tempfile
import unittest
from pathlib import Path
from tools.contract_inspector import (
    inspect_file,
    inspect_wsdl,
    inspect_openapi,
    local_ref,
    ContractError,
    MAX_BYTES,
)

FIXTURES = Path(__file__).parent / 'fixtures'


class ContractTests(unittest.TestCase):
    def test_json_fixture(self):
        result = inspect_file(FIXTURES / 'synthetic_openapi.json')
        self.assertFalse(result['production_approved'])
        self.assertEqual(result['status'], 'draft')
        self.assertEqual(len(result['sha256']), 64)

    def test_operation_overrides_path_parameter(self):
        result = inspect_file(FIXTURES / 'synthetic_openapi.json')
        params = result['operations'][0]['parameters']
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0]['schema']['minimum'], 1)
        self.assertTrue(params[0]['required'])

    def test_yaml_fixture(self):
        self.assertEqual(inspect_file(FIXTURES / 'synthetic_openapi.yml')['format'], 'openapi')

    def test_wsdl_fixture(self):
        result = inspect_file(FIXTURES / 'synthetic.wsdl')
        self.assertEqual(result['operations'], ['syntheticConsult'])
        self.assertEqual(result['imports_NOT_FETCHED'], ['https://example.invalid/schema.wsdl'])
        self.assertEqual(result['addresses_NOT_CALLED'], ['https://example.invalid/soap'])

    def test_html_rejected(self):
        with self.assertRaises(ContractError):
            inspect_wsdl(b'<html><body>Forbidden</body></html>')

    def test_dtd_rejected(self):
        with self.assertRaises(ContractError):
            inspect_wsdl(b'<!DOCTYPE definitions [<!ENTITY x "unsafe">]><definitions>&x;</definitions>')

    def test_external_refs_rejected(self):
        with self.assertRaises(ContractError):
            local_ref({}, {'$ref': 'https://example.invalid/schema'})

    def test_circular_refs_rejected(self):
        document = {'a': {'$ref': '#/b'}, 'b': {'$ref': '#/a'}}
        with self.assertRaisesRegex(ContractError, 'circular'):
            local_ref(document, {'$ref': '#/a'})

    def test_missing_ref_rejected(self):
        with self.assertRaises(ContractError):
            local_ref({}, {'$ref': '#/missing'})

    def test_escaped_json_pointer(self):
        self.assertEqual(local_ref({'a/b': {'~x': 3}}, {'$ref': '#/a~1b/~0x'}), 3)

    def test_non_openapi_rejected(self):
        for document in ({}, [], {'openapi': '3.0.3', 'paths': None}):
            with self.assertRaises(ContractError):
                inspect_openapi(document)

    def test_missing_file(self):
        with self.assertRaises(ContractError):
            inspect_file(FIXTURES / 'does-not-exist')

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'empty'
            p.write_bytes(b'')
            with self.assertRaises(ContractError):
                inspect_file(p)

    def test_oversized_contract(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'big'
            p.write_bytes(b' ' * (MAX_BYTES + 1))
            with self.assertRaises(ContractError):
                inspect_file(p)

    def test_unsafe_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'unsafe.yml'
            p.write_text('!!python/object/apply:os.system ["echo should-not-execute"]')
            with self.assertRaises(ContractError):
                inspect_file(p)
