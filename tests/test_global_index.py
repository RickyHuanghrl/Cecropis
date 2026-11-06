import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

from cecropis.case import ANNOTATIONS, WEIGHTS
from cecropis.global_index import GlobalIndex, build_global_index, resume_global_index


class GlobalIndexChecks(unittest.TestCase):
    def fixture(self, root):
        raw = root / 'raw'
        raw.mkdir()
        feather.write_feather(pa.Table.from_pylist([
            {'bodyId': 10, 'type': 'Input', 'instance': 'Neuron Alpha', 'status': 'Traced', 'class': 'sensory', 'somaSide': 'R'},
            {'bodyId': 20, 'type': 'Output', 'instance': 'Neuron Beta', 'status': 'Traced', 'class': 'motor', 'somaSide': 'L'},
            {'bodyId': 30, 'type': None, 'instance': None, 'status': 'Glia', 'class': None, 'somaSide': None},
            {'bodyId': 40, 'type': 'fragment', 'instance': None, 'status': 'Orphan', 'class': None, 'somaSide': None},
            {'bodyId': 9007199254741001, 'type': 'large ID', 'instance': None, 'status': 'Traced', 'class': None, 'somaSide': None},
        ]), raw / ANNOTATIONS)
        feather.write_feather(pa.table({'body_pre': pa.array([10, 99, 10, 20, 99], type=pa.int64()),
                                       'body_post': pa.array([20, 20, 20, 99, 30], type=pa.int64()),
                                       'weight': pa.array([2, 5, 3, 7, 11], type=pa.int64())}), raw / WEIGHTS)
        return raw

    def test_full_graph_unknown_endpoints_duplicates_and_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = build_global_index(self.fixture(root), root / 'index', batch_size=2)
            index = GlobalIndex(root / 'index')
            self.assertEqual(manifest['source_rows'], 5)
            self.assertEqual(manifest['edge_count'], 4)
            self.assertEqual(manifest['node_count'], 6)
            self.assertEqual(manifest['category_counts'], {'neuron': 3, 'glia': 1, 'other': 1, 'unannotated': 1})
            self.assertEqual(index.node('99')['category'], 'unannotated')
            self.assertEqual(index.node('20')['total_input'], 10)
            self.assertEqual(index.node('20')['total_output'], 7)
            upstream = index.neighbors('20', 'incoming')
            self.assertEqual(upstream['contacts'], 10)
            self.assertEqual(upstream['edge_count'], 2)
            self.assertEqual([(x['node']['bodyId'], x['weight']) for x in upstream['nodes']], [('10', 5), ('99', 5)])
            downstream = index.neighbors(99, 'outgoing', limit=1)
            self.assertEqual(downstream['contacts'], 16)
            self.assertEqual(downstream['edge_count'], 2)
            self.assertEqual(downstream['nodes'][0]['node']['bodyId'], '30')
            np.testing.assert_array_equal(index.total_input, np.asarray(index.incoming.sum(axis=1)).ravel())
            self.assertEqual(int(index.incoming.sum()), 28)
            self.assertTrue(index.ids.flags.writeable is False)
            self.assertEqual(index.annotations[10]['instance'], 'Neuron Alpha')
            index.close()

    def test_annotation_search_pagination_and_safe_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            build_global_index(self.fixture(root), root / 'index', batch_size=2)
            index = GlobalIndex(root / 'index')
            self.assertEqual(index.find({'q': 'alpha'})['nodes'][0]['bodyId'], '10')
            self.assertEqual(index.find({'type': 'Output', 'somaSide': 'L'})['total'], 1)
            self.assertEqual(index.find({'category': 'neuron'}, limit=1, offset=2)['nodes'][0]['bodyId'], '9007199254741001')
            self.assertEqual(index.find({'bodyId': '99'})['total'], 1)
            self.assertEqual(index.find({'q': '99'})['nodes'][0]['bodyId'], '99')
            self.assertEqual(index.find({})['total'], 6)
            self.assertEqual([node['bodyId'] for node in index.find({}, limit=2, offset=3)['nodes']], ['40', '99'])
            self.assertEqual(index.find({'category': 'unannotated'})['nodes'][0]['bodyId'], '99')
            self.assertEqual(index.find({'category': 'unannotated'}, offset=1)['nodes'], [])
            np.testing.assert_array_equal(index.ids_for({'category': 'unannotated'}), [99])
            np.testing.assert_array_equal(index.ids_for({'category': ['glia', 'unannotated']}), [30, 99])
            np.testing.assert_array_equal(index.ids_for({'category': 'neuron'}), [10, 20, 9007199254741001])
            self.assertEqual([node['bodyId'] for node in index.nodes([99, 20, 10])], ['99', '20', '10'])
            self.assertEqual(index.nodes([99])[0]['category'], 'unannotated')
            with self.assertRaises(ValueError):
                index.ids_for({'category': 'neuron'}, max_count=2)
            with self.assertRaises(KeyError):
                index.nodes([11])
            self.assertEqual(index.find({'q': "' OR 1=1 --"})['total'], 0)
            with self.assertRaises(ValueError):
                index.find({'made_up': 'x'})
            with self.assertRaises(ValueError):
                index.node('1.5')
            with self.assertRaises(FileExistsError):
                build_global_index(root / 'raw', root / 'index')
            index.close()

    def test_completed_staging_recovery_never_reopens_raw(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = self.fixture(root)
            destination = root / 'index'
            # Force a stop exactly after the only source scan. This creates the
            # production complete-scan marker, annotation DB and edge streams.
            with patch('cecropis.global_index._finalize_staging', side_effect=RuntimeError('interrupted after scan')):
                with self.assertRaises(RuntimeError):
                    build_global_index(raw, destination, batch_size=2)
            connection = sqlite3.connect(destination / 'annotations.sqlite')
            connection.execute('INSERT INTO nodes (bodyId, category) VALUES (99, ?)', ('unannotated',))
            connection.commit()
            connection.close()
            # A guard forbids even opening an Arrow dataset during recovery.
            with patch('cecropis.global_index.ds.dataset', side_effect=AssertionError('raw reread')):
                manifest = resume_global_index(destination, batch_size=2)
            self.assertTrue(manifest['resumed_from_staging'])
            index = GlobalIndex(destination)
            self.assertEqual(index.node('99')['total_input'], 7)
            self.assertEqual(index.find({'bodyId': '99'})['total'], 1)
            index.close()
            connection = sqlite3.connect(destination / 'annotations.sqlite')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM nodes').fetchone()[0], 5)
            connection.close()
            self.assertFalse((destination / 'stage_pre.bin').exists())


if __name__ == '__main__':
    unittest.main()
