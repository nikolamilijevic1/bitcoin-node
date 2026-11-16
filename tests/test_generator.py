import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from generate import plan_transaction, plan_batch, FEE


class Plans(unittest.TestCase):
    def test_batches_have_no_shared_inputs_and_respect_mining_boundaries(self):
        state = {'seed': 2026, 'target': 1000, 'addresses': [f'addr{i}' for i in range(256)],
                 'lanes': [{'txid': f'tx{i}', 'vout': 0, 'sats': 5000000000,
                            'address': f'lane{i}'} for i in range(64)]}
        completed = 0
        while completed < state['target']:
            state['completed'] = completed
            plans = plan_batch(state)
            self.assertTrue(plans)
            inputs = [(v['txid'], v['vout']) for p in plans for v in p[0]]
            self.assertEqual(len(inputs), len(set(inputs)))
            self.assertLessEqual(len(plans), 200 - completed % 200)
            completed += len(plans)
        self.assertEqual(completed, state['target'])

    def test_conservation_and_distinct_inputs(self):
        state = {'seed': 2026, 'addresses': [f'addr{i}' for i in range(256)],
                 'lanes': [{'txid': f'tx{i}', 'vout': 0, 'sats': 5000000000,
                            'address': f'lane{i}'} for i in range(64)]}
        seen = set()
        for n in range(1000):
            state['completed'] = n
            inputs, outputs, replacements, scenario, _ = plan_transaction(state)
            self.assertEqual(len(inputs), len({(i['txid'], i['vout']) for i in inputs}))
            total = sum(state['lanes'][r['index']]['sats'] for r in replacements)
            actual = sum(round(next(iter(o.values())) * 100000000) for o in outputs)
            self.assertEqual(total - actual, FEE)
            self.assertTrue(all(r['sats'] > 0 for r in replacements))
            seen.add(scenario)
        self.assertEqual(len(seen), 3)


if __name__ == '__main__':
    unittest.main()
