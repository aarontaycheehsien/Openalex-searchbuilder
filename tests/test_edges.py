import io
import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from test_workflow import Base, RECORDS
from osb.api import Client, ApiError
from osb.cli import main
from osb.core import Error
from osb.export import export
from osb.workflow import evaluate, critic_packet, check_critic

class EdgeTests(Base):
    def test_discovery_withholds_protected_record_text(self):
        self.ws.save_set('held', 'validation', ['W2'])
        with patch('osb.cli.Client', return_value=self.fake), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['-w', str(self.ws.root), 'sample', '--purpose', 'pilot']), 0)
            data = json.loads(output.getvalue())
            self.assertEqual(data['protected_records_withheld'], 1)
            self.assertEqual([r['id'] for r in data['records']], ['https://openalex.org/W1'])

    def test_resolve_and_missing_identifier(self):
        seen=[]
        class Response(io.BytesIO): headers={}
        def opener(req, timeout):
            seen.append(req.full_url)
            if '999' in req.full_url:
                raise HTTPError(req.full_url, 404, 'not found', {}, io.BytesIO(b'not found'))
            return Response(json.dumps(RECORDS[0]).encode())
        c=Client(self.ws, opener=opener, sleep=lambda n: None)
        self.assertEqual(c.resolve('10.1234/a')['id'], 'W1')
        self.assertIn('https%3A%2F%2Fdoi.org%2F10.1234%2Fa', seen[0])
        self.assertEqual(c.resolve('W999')['status'], 'unresolved')
        self.assertEqual(c.resolve('ambiguous title')['status'], 'unresolved')
    def test_api_contract_missing_fields(self):
        class Response(io.BytesIO): headers={}
        c=Client(self.ws, opener=lambda *a, **kw: Response(b'{}'), sleep=lambda n: None)
        with self.assertRaises(ApiError): c.validate({'get_rows':'works'})
        with self.assertRaises(ApiError): c.search({'get_rows':'works'})
    def test_duplicate_export_and_count_discrepancy(self):
        self.validated()
        def pages(q, **kw):
            cursor=kw['cursor']
            return {'results':[RECORDS[0]],'meta':{'count':2,'next_cursor':'1' if cursor=='*' else None}}
        self.fake.search=pages
        result=export(self.ws,self.fake)
        self.assertTrue(result['complete']); self.assertEqual(result['unique_records'],1)
        self.assertTrue(result['count_discrepancy'])
    def test_closing_round_keeps_findings(self):
        p=self.ws.get('protocol.json');p['depth']='quick';self.ws.put('protocol.json',p)
        evaluate(self.ws,self.fake); packet=critic_packet(self.ws)
        finding={'id':'F1','kind':'lexical','severity':'advisory','message':'Consider synonym',
                 'status':'rejected','response':'Not applicable to the defined scope'}
        review={**packet['response_template'],'reviewer':'reviewer','summary':'reviewed','findings':[finding]}
        check_critic(self.ws,review);self.ws.put('critic/review.json',review)
        closing=critic_packet(self.ws);self.assertEqual(closing['phase'],'closing')
        response={**closing['response_template'],'reviewer':'reviewer','summary':'closing','findings':[]}
        with self.assertRaises(Error):check_critic(self.ws,response)
        response['findings']=[finding];check_critic(self.ws,response)
    def test_protected_fetch_does_not_issue_request(self):
        self.ws.save_set('held','validation',['W2'])
        with patch('urllib.request.urlopen', side_effect=AssertionError('must not request')), patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(['-w',str(self.ws.root),'fetch','W2']),1)
    def test_scope_change_and_api_failure_block_delivery(self):
        self.validated()
        p=self.ws.get('protocol.json');p['scope_confirmed']=False;self.ws.put('protocol.json',p)
        self.assertFalse(self.ws.get('evaluation.json')['input_sha256']==self.ws.fingerprint())
        def fail(*a,**kw):raise ApiError('unavailable')
        self.fake.validate=fail
        e=evaluate(self.ws,self.fake)
        self.assertFalse(e['ok']);self.assertIn('unavailable',e['error'])
