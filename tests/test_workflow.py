import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from osb.core import Workspace, Error, digest, work_id
from osb.strategy import prepare, parse, render
from osb.api import Client, ApiError, abstract
from osb.workflow import draft, evaluate, critic_packet, check_critic, report, terms
from osb.export import export
from osb.cli import main

RECORDS = [
    {'id': 'https://openalex.org/W1', 'display_name': 'Urban trees reduce heat', 'is_xpac': False,
     'publication_year': 2024, 'type': 'article', 'doi': 'https://doi.org/10.1234/a',
     'authorships': [{'author': {'display_name': 'Zoë Example'}}],
     'abstract_inverted_index': {'Urban': [0], 'trees': [1], 'heat': [2]},
     'primary_location': {'source': {'display_name': 'Cities'}, 'landing_page_url': 'https://example.org/a'}},
    {'id': 'https://openalex.org/W2', 'display_name': 'Trees and learning', 'is_xpac': True,
     'keywords': [{'display_name': 'heat'}], 'fulltext': 'urban heat', 'type': 'book'},
    {'id': 'https://openalex.org/W3', 'display_name': 'Urban education', 'is_xpac': False,
     'abstract_inverted_index': None, 'fulltext': 'trees heat', 'type': 'dissertation'},
]

class Fake:
    """Small deterministic fixture, not an emulator of OpenAlex linguistic matching."""
    def __init__(self, records=None):
        self.records = copy.deepcopy(RECORDS if records is None else records)
        self.calls = []
    def matches(self, r, node):
        if 'join' in node:
            vals = [self.matches(r, n) for n in node['filters']]
            value = all(vals) if node['join'] == 'and' else any(vals)
        else:
            key, wanted = node['column_id'], node['value']
            if key == 'id': value = work_id(r['id']) == wanted
            elif '.search' in key:
                text = r.get('display_name', '') + ' ' + abstract(r)
                if key.startswith(('title_abstract_keywords', 'fulltext')):
                    text += ' ' + ' '.join(k['display_name'] for k in r.get('keywords', []))
                if key.startswith('fulltext'): text += ' ' + r.get('fulltext', '')
                def expression(node):
                    if node[0] == 'term': return node[1].strip('"').casefold() in text.casefold()
                    if node[0] == 'not': return not expression(node[1])
                    values = [expression(n) for n in node[1:]]
                    return all(values) if node[0] == 'and' else any(values)
                value = expression(parse(str(wanted)))
            else: value = r.get(key) == wanted
        return not value if node.get('is_negated') else value
    def selected(self, q):
        return [r for r in self.records if (q['corpus'] != 'core' or not r.get('is_xpac'))
                and all(self.matches(r, n) for n in q.get('filter_rows', []))]
    def validate(self, q):
        self.calls.append(('validate', q))
        return {'oqo': q, 'oql': 'fixture canonical ' + digest(q), 'validation': {'valid': True, 'warnings': []}}
    def search(self, q, per_page=1, cursor=None, select=None):
        self.calls.append(('search', q, cursor))
        rows = self.selected(q)
        start = 0 if cursor in {None, '*'} else int(cursor)
        size = 1 if cursor is not None else per_page
        return {'results': rows[start:start+size], 'meta': {'count': len(rows),
                    'next_cursor': str(start+size) if start+size < len(rows) else None}}
    def among(self, q, ids):
        return {work_id(r['id']) for r in self.selected(q)} & set(ids)
    def fetch(self, ids):
        return [r for r in self.records if work_id(r['id']) in ids]

class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace.create(Path(self.temp.name) / 'run', 'Do urban trees reduce heat?')
        p = self.ws.get('protocol.json'); p['scope_confirmed'] = True
        p['concepts'] = [{'id': 'trees', 'role': 'search', 'name': 'trees', 'rationale': 'intervention'},
                         {'id': 'heat', 'role': 'search', 'name': 'heat', 'rationale': 'phenomenon'}]
        self.ws.put('protocol.json', p)
        s = self.ws.get('strategy.json'); s['blocks'] = [{'id': 'trees', 'name': 'trees', 'terms': ['trees']},
                                                       {'id': 'heat', 'name': 'heat', 'terms': ['heat']}]
        self.ws.put('strategy.json', s)
        self.fake = Fake()
    def validated(self):
        e = evaluate(self.ws, self.fake)
        self.assertTrue(e['ok'], e)
        packet = critic_packet(self.ws)
        review = {**packet['response_template'], 'reviewer': 'test reviewer', 'summary': 'Fixture review only; no empirical claims.'}
        check_critic(self.ws, review)
        self.ws.put('critic/review.json', review)
        return report(self.ws, self.fake)

class DraftTests(Base):
    def test_offline_generation_and_transition(self):
        p = self.ws.get('protocol.json'); p['mode'] = 'draft'; self.ws.put('protocol.json', p)
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
            result = draft(self.ws)
            self.assertEqual('untested', result['status'])
            self.assertNotIn('count', result)
            self.assertFalse((self.ws.root / 'validation-manifest.json').exists())
            with self.assertRaises(Error): Client(self.ws)
            with self.assertRaises(Error): evaluate(self.ws, self.fake)
        p['mode'] = 'validated'; self.ws.put('protocol.json', p)
        self.assertTrue((self.ws.root / 'draft-query.txt').exists())
        with self.assertRaises(Error): report(self.ws, self.fake)
        self.validated()
    def test_incompatible_workspace(self):
        self.ws.put('workspace.json', {'provider': 'pubmed'})
        with self.assertRaises(Error): Workspace(self.ws.root)
    def test_cli_offline(self):
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            rc = main(['-w', str(self.ws.root), 'mode', 'draft'])
            self.assertEqual(rc, 0)
        with patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['-w', str(self.ws.root), 'count']), 1)
            self.assertIn('offline', output.getvalue())
            self.assertEqual(main(['-w', str(self.ws.root), 'draft']), 0)

class StrategyTests(Base):
    def test_preserves_text_context_in_one_search_leaf(self):
        s = self.ws.get('strategy.json')
        s['blocks'][0]['terms'] = ['remote work productivity', '"urban trees"']
        query = prepare(s)
        leaves = query['oqo']['filter_rows']
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0]['operator'], 'has')
        self.assertIn('(remote work productivity)', leaves[0]['value'])
        self.assertNotIn('remote AND work', leaves[0]['value'])
        self.assertEqual(leaves[0]['value'], query['boolean'])

    def test_standalone_proximity_leaf(self):
        query = prepare({'blocks': [{'id': 'topic', 'terms': ['"climate change"~3']}],
                         'search_fields': 'title_abstract'})
        self.assertEqual(query['oqo']['filter_rows'], [
            {'column_id': 'title_and_abstract.search', 'operator': 'has', 'value': '"climate change"~3'}])

    def test_three_modes_and_corpus(self):
        s = self.ws.get('strategy.json')
        for mode, count in [('title_abstract', 1), ('title_abstract_keywords', 2), ('fulltext', 3)]:
            s['search_fields'] = mode
            self.assertEqual(len(self.fake.selected(prepare(s)['oqo'])), count)
        s['corpus'] = 'core'
        self.assertEqual(len(self.fake.selected(prepare(s)['oqo'])), 2)
    def test_nesting_and_negation(self):
        self.assertEqual(render(parse('trees OR heat AND NOT urban')), '(trees OR (heat AND NOT (urban)))')
        self.assertEqual(render(parse('(trees OR heat) NOT urban')), '((trees OR heat) AND NOT (urban))')
        for bad in ['trees AND', '(trees', 'trees)', '"trees', 'trees[tiab]', 'trees and heat']:
            with self.subTest(bad=bad), self.assertRaises(Error): parse(bad)
    def test_wildcards_and_proximity(self):
        s = self.ws.get('strategy.json'); s['blocks'][0]['terms'] = ['tree*']
        with self.assertRaises(Error): prepare(s)
        s['matching'] = 'exact'; prepare(s)
        s['blocks'][0]['terms'] = ['tr*']
        with self.assertRaises(Error): prepare(s)
        s['blocks'][0]['terms'] = ['"urban trees"~5']; prepare(s)
        s['blocks'][0]['terms'] = ['"urban tree*"~5']
        with self.assertRaises(Error): prepare(s)
    def test_structured_filter_and_large_query(self):
        s = self.ws.get('strategy.json')
        s['limits'] = [{'filter': {'column_id': 'publication_year', 'value': 2024}, 'rationale': 'protocol year'}]
        self.assertEqual(len(self.fake.selected(prepare(s)['oqo'])), 1)
        s['blocks'][0]['terms'] = ['term' + str(i) for i in range(1200)]
        # Compiler must handle large OR lists without recursion failures.
        prepare(s)

class WorkflowTests(Base):
    def test_recall_coverage_and_misses(self):
        self.ws.save_set('seeds', 'seed', ['W1', 'W2', 'W3', 'W999'])
        e = evaluate(self.ws, self.fake)
        self.assertTrue(e['ok'], e)
        self.assertEqual(e['sets']['seeds']['retrieved'], 2)
        self.assertEqual(e['sets']['seeds']['unavailable'], ['W999'])
        self.assertEqual(e['misses'][0]['id'], 'W3')
        self.assertEqual(e['misses'][0]['failing_blocks'], ['trees', 'heat'])
    def test_outside_core_is_not_query_miss(self):
        self.ws.save_set('seeds', 'seed', ['W1', 'W2'])
        s = self.ws.get('strategy.json'); s['corpus'] = 'core'; self.ws.put('strategy.json', s)
        e = evaluate(self.ws, self.fake)
        self.assertEqual(e['sets']['seeds']['outside_corpus'], ['W2'])
        self.assertEqual(e['sets']['seeds']['relative_recall_percent'], 100)
    def test_holdout_protection_and_screening(self):
        self.ws.save_set('held', 'validation', ['W2'])
        self.ws.save_set('seed', 'seed', ['W1'])
        with self.assertRaises(Error): self.ws.save_set('leak', 'seed', ['W2'])
        with self.assertRaises(Error): self.ws.save_set('found', 'relevant', ['W3'])
        result = terms(self.ws, self.fake)
        self.assertEqual(result['development_ids'], ['W1'])
    def test_delivery_gate_and_staleness(self):
        with self.assertRaises(Error): report(self.ws, self.fake)
        self.validated()
        s = self.ws.get('strategy.json'); s['corpus'] = 'core'; self.ws.put('strategy.json', s)
        with self.assertRaises(Error): report(self.ws, self.fake)
        with self.assertRaises(Error): export(self.ws, self.fake)
    def test_live_drift_requires_re_review(self):
        self.validated()
        self.ws.save_set('seeds', 'seed', ['W1'])
        self.validated()
        changed = Fake([RECORDS[1]])
        with self.assertRaises(Error): report(self.ws, changed)
    def test_regression_needs_reason(self):
        self.ws.save_set('seeds', 'seed', ['W1', 'W2']); evaluate(self.ws, self.fake)
        s = self.ws.get('strategy.json'); s['search_fields'] = 'title_abstract'; self.ws.put('strategy.json', s)
        e = evaluate(self.ws, self.fake)
        self.assertFalse(e['ok']); self.assertIn('provide a reason', e['error'])
        self.assertTrue(evaluate(self.ws, self.fake, note='Documented field restriction')['ok'])
    def test_unresolved_technical_review_blocks(self):
        evaluate(self.ws, self.fake); p = critic_packet(self.ws)
        r = {**p['response_template'], 'reviewer': 'reviewer', 'summary': 'reviewed', 'findings': [
            {'id': 'F1', 'kind': 'technical', 'severity': 'must-fix', 'message': 'broken syntax', 'status': 'accepted-risk', 'response': 'ignore'}]}
        with self.assertRaises(Error): check_critic(self.ws, r)

class ExportTests(Base):
    def test_complete_unicode_and_ris(self):
        self.validated(); result = export(self.ws, self.fake)
        self.assertTrue(result['complete']); self.assertEqual(result['unique_records'], 2)
        folder = Path(result['directory'])
        self.assertIn('Zoë Example', (folder / 'results.ris').read_text(encoding='utf-8'))
        self.assertIn('DO  - 10.1234/a', (folder / 'results.ris').read_text(encoding='utf-8'))
        self.assertFalse(result['count_discrepancy'])
    def test_interrupt_and_resume(self):
        self.validated()
        original = self.fake.search
        def flaky(q, **kwargs):
            if kwargs.get('cursor') == '1': raise ApiError('quota exhausted')
            return original(q, **kwargs)
        self.fake.search = flaky
        result = export(self.ws, self.fake)
        self.assertFalse(result['complete']); self.assertEqual(result['unique_records'], 1)
        self.assertIn('results.partial.csv', result['files'])
        self.fake.search = original
        result = export(self.ws, self.fake)
        self.assertTrue(result['complete']); self.assertEqual(result['unique_records'], 2)
    def test_tampered_artifact_blocks(self):
        self.validated(); (self.ws.root / 'final-query.txt').write_text('tampered')
        with self.assertRaises(Error): export(self.ws, self.fake)
    def test_repeated_cursor_is_incomplete(self):
        self.validated()
        self.fake.search = lambda *a, **kw: {'results': [RECORDS[0]], 'meta': {'count': 2, 'next_cursor': '*'}}
        self.assertFalse(export(self.ws, self.fake)['complete'])

class TransportTests(Base):
    def test_post_auth_cache_and_redaction(self):
        requests = []
        class Response(io.BytesIO):
            headers = {'X-RateLimit-Credits-Used': '10'}
        def opener(req, timeout):
            requests.append(req)
            return Response(json.dumps({'results': [], 'meta': {'count': 0}, 'echo': 'secret-key'}).encode())
        with patch.dict(os.environ, {'OPENALEX_API_KEY': 'secret-key'}):
            client = Client(self.ws, opener=opener, sleep=lambda n: None)
            q = prepare(self.ws.get('strategy.json'))['oqo']
            client.search(q); client.search(q)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].method, 'POST')
            self.assertEqual(requests[0].get_header('Authorization'), 'Bearer secret-key')
            self.assertNotIn('secret-key', (self.ws.root / 'requests.jsonl').read_text())
            self.assertNotIn('secret-key', next((self.ws.root / '.cache').glob('*')).read_text())
            client.fresh = True; client.search(q); self.assertEqual(len(requests), 2)
    def test_quota_no_retry_and_transient_retry(self):
        attempts = []
        def fail(req, timeout):
            attempts.append(1)
            raise HTTPError(req.full_url, 429, 'Rate limited', {}, io.BytesIO(b'daily budget exhausted'))
        c = Client(self.ws, opener=fail, sleep=lambda n: None)
        with self.assertRaises(ApiError): c.request('/works')
        self.assertEqual(len(attempts), 1)
        def transient(req, timeout):
            attempts.append(1)
            raise HTTPError(req.full_url, 503, 'unavailable', {}, io.BytesIO(b'try later'))
        c.opener = transient
        with self.assertRaises(ApiError): c.request('/works')
        self.assertEqual(len(attempts), 5)
    def test_missing_metadata(self):
        self.assertEqual(abstract({'abstract_inverted_index': None}), '')
        self.assertEqual(abstract(RECORDS[0]), 'Urban trees heat')

if __name__ == '__main__': unittest.main()
