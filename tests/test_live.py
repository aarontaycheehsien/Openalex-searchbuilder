"""Opt-in integration checks. Never run automatically without explicit OSB_LIVE_TESTS=1."""
import os
from pathlib import Path
import tempfile
import unittest
from osb.api import Client
from osb.config import read_env
from osb.core import Workspace, work_id
from osb.strategy import prepare
from osb.workflow import evaluate, critic_packet, check_critic, report
from osb.export import export

@unittest.skipUnless(os.environ.get('OSB_LIVE_TESTS') == '1' and read_env('OPENALEX_API_KEY'),
                     'Live integration unverified: requires OSB_LIVE_TESTS=1 and OPENALEX_API_KEY')
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
            self.assertGreater(len(__import__('json').dumps(long_q)), 8190)
            client.search(client.validate(long_q)['oqo'])
            strategy['limits'] = [{'filter': {'column_id': 'id', 'value': ids[-1]}, 'rationale': 'One-record export smoke test'}]
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
