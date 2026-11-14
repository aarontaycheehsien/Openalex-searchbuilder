from test_workflow import Base, Fake, RECORDS
from osb.core import Error
from osb.workflow import evaluate, critic_packet, check_critic, report
from osb.export import export
from osb.api import ApiError

class RecheckTests(Base):
    def test_new_validation_does_not_reuse_completed_export(self):
        self.validated()
        first = export(self.ws, self.fake)
        changed = Fake([*RECORDS, {'id': 'https://openalex.org/W4', 'display_name': 'trees heat', 'is_xpac': False}])
        report(self.ws, changed)
        second = export(self.ws, changed)
        self.assertNotEqual(first['directory'], second['directory'])
        self.assertEqual(first['unique_records'], 2)
        self.assertEqual(second['unique_records'], 3)
        resumed = export(self.ws, changed)
        self.assertEqual(second['directory'], resumed['directory'])

    def test_failed_report_revokes_current_delivery(self):
        self.validated()
        def unavailable(*a, **kw): raise ApiError('Service unavailable')
        self.fake.validate = unavailable
        with self.assertRaises(Error): report(self.ws, self.fake)
        self.assertIsNone(self.ws.get('validation-manifest.json'))
        self.assertTrue(list((self.ws.root / 'history').glob('delivery-*.json')))
        with self.assertRaises(Error): export(self.ws, self.fake)

    def test_revision_cannot_drop_prior_objection(self):
        evaluate(self.ws, self.fake)
        packet = critic_packet(self.ws)
        finding = {'id': 'F1', 'kind': 'scope', 'severity': 'must-fix', 'message': 'Scope concern',
                   'status': 'open', 'response': ''}
        review = {**packet['response_template'], 'reviewer': 'reviewer', 'summary': 'reviewed', 'findings': [finding]}
        self.ws.put('critic/review.json', review)
        packet = critic_packet(self.ws)
        dropped = {**packet['response_template'], 'reviewer': 'reviewer', 'summary': 'reviewed', 'findings': []}
        with self.assertRaises(Error): check_critic(self.ws, dropped)

    def test_update_gets_new_review_budget(self):
        p = self.ws.get('protocol.json'); p['depth'] = 'quick'; self.ws.put('protocol.json', p)
        self.validated()
        s = self.ws.get('strategy.json'); s['corpus'] = 'core'; self.ws.put('strategy.json', s)
        self.assertTrue(evaluate(self.ws, self.fake)['ok'])
        packet = critic_packet(self.ws)
        self.assertEqual(packet['round'], 2)
        self.assertEqual(packet['cycle_round'], 1)
        self.assertEqual(packet['phase'], 'revision')

    def test_diagnostic_reports_blockers_without_delivery(self):
        result = report(self.ws, self.fake, diagnostic=True)
        self.assertFalse(result['ok'])
        self.assertTrue(result['blockers'])
        self.assertIsNone(self.ws.get('validation-manifest.json'))
