import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyarrow as pa
from scipy import sparse

from cecropis.case import extract_batches, normalize_counts
from cecropis.simulation import Experiment, compare, save_run


class CoreChecks(unittest.TestCase):
    def test_batches_preserve_external_denominator_and_direction(self):
        # Large IDs must remain int64. Duplicate 10->20 spans batches.
        ids = np.array([9007199254741001, 9007199254741002], dtype=np.int64)
        def batch(pre, post, weight):
            return pa.record_batch([pa.array(pre, type=pa.int64()),
                                    pa.array(post, type=pa.int64()),
                                    pa.array(weight, type=pa.int64())],
                                   names=['body_pre', 'body_post', 'weight'])
        chunks = iter([batch([ids[0], 3], [ids[1], ids[1]], [2, 5]),
                       batch([ids[0], ids[1]], [ids[1], 4], [3, 7])])
        counts, totals, stats = extract_batches(ids, chunks)
        np.testing.assert_array_equal(totals['total_input'], [0, 10])
        np.testing.assert_array_equal(totals['external_input'], [0, 5])
        np.testing.assert_array_equal(totals['external_output'], [0, 7])
        self.assertEqual(counts[1, 0], 5)
        self.assertEqual(counts[0, 1], 0)
        self.assertEqual(stats['duplicate_internal_rows'], 1)
        np.testing.assert_array_equal(normalize_counts(counts, totals['total_input']) @ [1, 0], [0, .5])

    def fixture(self):
        nodes = [{'bodyId': 10, 'role': 'input', 'type': 'PN'},
                 {'bodyId': 20, 'role': 'internal', 'type': 'KC'},
                 {'bodyId': 30, 'role': 'output', 'type': 'A'},
                 {'bodyId': 40, 'role': 'output', 'type': 'B'}]
        matrix = sparse.csr_matrix(([.5, .4, .2], ([1, 2, 3], [0, 1, 1])), shape=(4, 4))
        case = {'nodes': nodes, 'matrix': matrix, 'manifest': {'case_id': 'test-case'}}
        cfg = Experiment(steps=20, input_group='PN', input_start=0, input_stop=8,
                         intervention_group='KC', intervention_start=3,
                         intervention_stop=6, gain=0, outputs=('A', 'B'))
        return case, cfg

    def test_timing_zero_intervention_and_replay(self):
        case, cfg = self.fixture()
        result = compare(case, cfg, keep_states=True)
        b, i = result.pop('states')
        np.testing.assert_array_equal(b[:4], i[:4])
        np.testing.assert_array_equal(i[4:7, 1], 0)
        self.assertGreater(i[7, 1], 0)
        self.assertGreater(b[:, 2].max(), 0)
        cfg.gain = 1
        zero = compare(case, cfg, keep_states=True)
        np.testing.assert_array_equal(*zero['states'])
        with tempfile.TemporaryDirectory() as tmp:
            result = compare(case, cfg)
            folder = save_run(Path(tmp), result)
            restored = Experiment.from_dict(json.loads((folder / 'config.json').read_text())['experiment'])
            replay = compare(case, restored)
            self.assertEqual(result['series'], replay['series'])
            self.assertEqual(result['summary'], replay['summary'])

    def test_invalid_config_is_rejected(self):
        case, cfg = self.fixture()
        for key, value in [('gain', float('nan')), ('steps', 0), ('steps', 20.5),
                           ('input_stop', 21), ('intervention_group', 'PN'),
                           ('outputs', ('A', 'A'))]:
            with self.subTest(key=key):
                old = getattr(cfg, key)
                setattr(cfg, key, value)
                with self.assertRaises(ValueError):
                    compare(case, cfg)
                setattr(cfg, key, old)


if __name__ == '__main__':
    unittest.main()
