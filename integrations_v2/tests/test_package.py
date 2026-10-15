import json
import re
import unittest
from pathlib import Path
from tools.contract_inspector import inspect_file, local_ref

ROOT = Path(__file__).resolve().parents[1]
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}


def walk(value):
    yield value
    if isinstance(value, dict):
        for x in value.values():
            yield from walk(x)
    elif isinstance(value, list):
        for x in value:
            yield from walk(x)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.cat = json.loads((ROOT / '02_CATALOGO_APIS.json').read_text(encoding='utf-8'))
        self.spec = json.loads((ROOT / 'openapi/jumbi-integrations.openapi.json').read_text(encoding='utf-8'))

    def test_all_json_files_parse(self):
        for p in ROOT.rglob('*.json'):
            with self.subTest(file=p.name):
                json.loads(p.read_text(encoding='utf-8'))

    def test_inventory_is_27_tj_and_6_trf(self):
        entries = json.loads((ROOT / '03_REGISTRO_TRIBUNAIS.json').read_text(encoding='utf-8'))['entries']
        self.assertEqual(len(entries), 33)
        self.assertEqual(len({e['tribunal'] for e in entries}), 33)
        self.assertEqual(sum(e['branch'] == 'estadual' for e in entries), 27)
        self.assertEqual(sum(e['branch'] == 'federal' for e in entries), 6)

    def test_inventory_not_live(self):
        entries = json.loads((ROOT / '03_REGISTRO_TRIBUNAIS.json').read_text(encoding='utf-8'))['entries']
        self.assertTrue(all(e['live_integration'] is False and e['case_api_endpoint'] is None for e in entries))

    def test_no_external_enablement_presumed(self):
        for k in ('domicilio', 'tpu', 'bnp_optional', 'cnj_consolidated_data', 'datajud', 'previdia_inss'):
            self.assertIs(self.cat[k]['enabled'], False)
        self.assertIsNone(self.cat['domicilio']['api_base_production'])
        self.assertIs(self.cat['djen']['openapi_downloaded'], False)

    def test_mni_documents_not_automatic_credentials(self):
        instances = self.cat['mni']['instances']
        self.assertEqual(len(instances), 3)
        self.assertTrue(all(e['enabled'] is False for e in instances))

    def test_internal_openapi_has_17_unique_operations(self):
        ops = [v[m] for v in self.spec['paths'].values() for m in v if m in METHODS]
        self.assertEqual(len(self.spec['paths']), 14)
        self.assertEqual(len(ops), 17)
        self.assertEqual(len({o['operationId'] for o in ops}), 17)

    def test_all_internal_refs_resolve(self):
        for value in walk(self.spec):
            if isinstance(value, dict) and '$ref' in value:
                with self.subTest(ref=value['$ref']):
                    local_ref(self.spec, value)

    def test_every_path_parameter_declared(self):
        for path, entry in self.spec['paths'].items():
            for method, op in entry.items():
                if method not in METHODS:
                    continue
                params = [local_ref(self.spec, p) for p in entry.get('parameters', []) + op.get('parameters', [])]
                for name in re.findall(r'{([^}]+)}', path):
                    with self.subTest(path=path, method=method, name=name):
                        self.assertTrue(any(p.get('name') == name and p.get('in') == 'path' and p.get('required') is True for p in params))

    def test_internal_schema_inspector(self):
        result = inspect_file(ROOT / 'openapi/jumbi-integrations.openapi.json')
        self.assertEqual(len(result['operations']), 17)
        self.assertFalse(result['production_approved'])

    def test_required_handoff_files(self):
        for name in ('00_PROMPT_PARA_CODEX.txt', '01_ESPECIFICACAO_EXECUTAVEL.md', '04_CHECKLIST_ACEITE.md', '05_PENDENCIAS_EXTERNAS.md', '.env.integrations.example', 'LEIA_PRIMEIRO.md'):
            self.assertTrue((ROOT / name).is_file())

    def test_source_ids_are_resolved(self):
        sources = json.loads((ROOT / 'sources/catalogo_fontes.json').read_text(encoding='utf-8'))
        ids = {s['id'] for s in sources}
        self.assertEqual(len(sources), len(ids))
        for value in walk(self.cat):
            if isinstance(value, dict):
                for code in value.get('sources', []):
                    self.assertIn(code, ids)
                if 'source' in value:
                    self.assertIn(value['source'], ids)
