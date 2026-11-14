"""Opt-in integration checks. Never run automatically without explicit OSB_LIVE_TESTS=1."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from osb.api import ApiError, Client
from osb.config import read_env
from osb.core import Workspace, work_id
from osb.strategy import prepare
from osb.workflow import evaluate, critic_packet, check_critic, report
from osb.export import export

@unittest.skipUnless(os.environ.get('OSB_LIVE_TESTS') == '1' and read_env('OPENALEX_API_KEY'),
                     'Requires OSB_LIVE_TESTS=1 and OPENALEX_API_KEY')
class LiveContractTests(unittest.TestCase):
    def test_api_modes_intersection_long_query_and_small_export(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Workspace.create(Path(directory) / 'live', 'API contract smoke test, not a research strategy')
            client = Client(ws, fresh=True)
            strategy = ws.get('strategy.json')
            strategy['blocks'] = [{'id': 'topic', 'name': 'climate', 'terms': ['"climate change"']}]
            ids = []
            for mode in ['title_abstract', 'title_abstract_keywords', 'fulltext']:
                strategy['search_fields'] = mode
                q = prepare(strategy)['oqo']
                checked = client.validate(q)
                data = client.search(checked['oqo'])
                self.assertGreater(data['meta']['count'], 0)
                identifier = work_id(data['results'][0]['id'])
                self.assertIn(identifier, client.among(q, [identifier]))
                ids.append(identifier)
            expansion = {**q, 'corpus': 'expansion'}
            expansion_data = client.search(client.validate(expansion)['oqo'])
            self.assertGreater(expansion_data['meta']['count'], 0)
            self.assertTrue(expansion_data['results'][0]['is_xpac'])
            long_s = {**strategy, 'search_fields': 'title_abstract', 'blocks': [
                {'id': 'topic', 'terms': ['"climate change"'] * 400}]}
            long_q = prepare(long_s)['oqo']
            self.assertGreater(len(json.dumps(long_q).encode()), 8190)
            client.search(client.validate(long_q)['oqo'])
            strategy['limits'] = [{'filter': {'column_id': 'ids.openalex', 'value': ids[-1]}, 'rationale': 'One-record export smoke test'}]
            ws.put('strategy.json', strategy)
            p = ws.get('protocol.json'); p['scope_confirmed'] = True
            p['concepts'] = [{'id': 'topic', 'name': 'climate', 'role': 'search', 'rationale': 'Contract test'}]
            ws.put('protocol.json', p); ws.save_set('known', 'seed', [ids[-1]])
            e = evaluate(ws, client)
            self.assertTrue(e['ok'], e)
            packet = critic_packet(ws)
            review = {**packet['response_template'], 'reviewer': 'automated contract test', 'fresh_context': False,
                      'summary': 'Transport-only smoke test. Not a scholarly search review.'}
            check_critic(ws, review); ws.put('critic/review.json', review)
            report(ws, client)
            out = export(ws, client)
            self.assertTrue(out['complete']); self.assertEqual(out['unique_records'], 1)

    def test_wildcard_proximity_and_resumed_export(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Workspace.create(Path(directory) / 'live', 'Bounded cursor and syntax check')
            client = Client(ws, fresh=True)
            for matching, term in [('exact', 'climat*'), ('stemmed', '"climate change"~3')]:
                strategy = {**ws.get('strategy.json'), 'search_fields': 'title_abstract',
                            'matching': matching, 'blocks': [{'id': 'topic', 'terms': [term]}]}
                checked = client.validate(prepare(strategy)['oqo'])
                data = client.search(checked['oqo'], per_page=2, select='id')
                self.assertEqual(len(data['results']), 2)
            ids = {work_id(row['id']) for row in data['results']}
            query = {'get_rows': 'works', 'corpus': 'all', 'filter_rows': [
                {'join': 'or', 'filters': [{'column_id': 'ids.openalex', 'value': i}
                                          for i in sorted(ids)]}]}
            query = client.validate(query)['oqo']
            # Isolate cursor traversal. The other test builds a full validated report.
            ws.put('validation-manifest.json', {'ok': True, 'input_sha256': ws.fingerprint(),
                                                'oqo': query, 'count': 2, 'files': {}})
            search = client.search
            cursors = []
            def one_row(q, *, cursor, per_page):
                cursors.append(cursor)
                if len(cursors) == 2:
                    raise ApiError('Intentional interruption before second page')
                if len(cursors) > 4:
                    raise ApiError('Exceeded live cursor request limit')
                return search(q, cursor=cursor, per_page=1)
            with patch.object(client, 'search', side_effect=one_row):
                partial = export(ws, client)
                self.assertFalse(partial['complete'])
                self.assertEqual(partial['unique_records'], 1)
                result = export(ws, client)
            self.assertTrue(result['complete'], result['error'])
            self.assertEqual(cursors[1], cursors[2])
            self.assertEqual(result['unique_records'], 2)
            rows = (Path(result['directory']) / 'results.jsonl').read_text(encoding='utf-8')
            self.assertEqual({work_id(json.loads(row)['id']) for row in rows.splitlines()}, ids)

    def test_compound_native_proximity_matches_posted_oql(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Workspace.create(Path(directory) / 'live', 'Compound proximity comparison')
            client = Client(ws, fresh=True)
            oql = ('get works (all corpora) with ((climate and change within 3 words '
                   'of each other) OR climatology) in the title or abstract')
            expected = client.request('/query', {'oql': oql})
            strategy = {'search_fields': 'title_abstract', 'proximity_mode': 'oql',
                        'blocks': [{'id': 'topic', 'terms': ['"climate change"~3', 'climatology']}]}
            actual = client.validate(prepare(strategy)['oqo'])
            self.assertEqual(actual['oqo'], expected['oqo'])
            self.assertEqual(actual['oql'], expected['oql'])
            posted = client.request('/', {'oql': actual['oql'], 'per_page': 3, 'select': 'id'})
            executed = client.search(actual['oqo'], per_page=3, select='id')
            self.assertGreater(executed['meta']['count'], 0)
            self.assertEqual(executed['meta']['count'], posted['meta']['count'])
            self.assertEqual(executed['results'], posted['results'])
