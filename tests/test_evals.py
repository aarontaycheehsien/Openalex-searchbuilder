import json
from pathlib import Path
import unittest
from test_workflow import Fake
from osb.strategy import prepare
from osb.core import work_id

class FixtureTests(unittest.TestCase):
    def test_separate_development_and_heldout(self):
        root = Path(__file__).resolve().parents[1] / 'evals'
        seen = set()
        for split in ('development', 'heldout'):
            for case in json.loads((root / (split + '.json')).read_text()):
                with self.subTest(split=split, topic=case['topic']):
                    self.assertNotIn(case['topic'], seen)
                    seen.add(case['topic'])
                    self.assertTrue(case['synthetic'])
                    fake = Fake(case['records'])
                    result = fake.selected(prepare(case['strategy'])['oqo'])
                    self.assertEqual(sorted(work_id(r['id']) for r in result), case['expected_ids'])
