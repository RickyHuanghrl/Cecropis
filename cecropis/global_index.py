"""Reusable complete graph index, built with one batched source-weights scan.

Rows are receivers in incoming CSR and senders in outgoing CSR. Integer counts
are retained, including unknown annotation endpoints; no analysis-case filter is
applied here. Edge staging is on disk and never accumulates Python edge lists.
"""
import gc
import json
import math
import numbers
import shutil
import sqlite3
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.dataset as ds
from scipy import sparse

from .case import ANNOTATIONS, WEIGHTS

FORMAT_VERSION = 'malecns-global-index-v1'
FILTER_FIELDS = ('name', 'type', 'class', 'status', 'statusLabel', 'superclass',
                 'subclass', 'supertype', 'somaSide', 'somaNeuromere', 'rootSide',
                 'instance', 'entryNerve', 'exitNerve', 'receptorType', 'category')


def _body_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, numbers.Integral)):
        raise ValueError('body ID must be a positive integer or decimal string')
    if isinstance(value, str) and (not value.isdecimal() or not value):
        raise ValueError('body ID must be a positive integer or decimal string')
    number = int(value)
    if number <= 0 or number > np.iinfo(np.int64).max:
        raise ValueError('body ID outside positive int64 range')
    return number


def _clean_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_json(item) for item in value]
    return value


def _category(node):
    if node.get('status') == 'Traced':
        return 'neuron'
    if node.get('status') == 'Glia':
        return 'glia'
    return 'other'


def _save_array(path, value, chunk=1000000):
    target = np.lib.format.open_memmap(path, mode='w+', dtype=value.dtype, shape=value.shape)
    for start in range(0, len(value), chunk):
        target[start:start + chunk] = value[start:start + chunk]
    target.flush()
    del target


def _save_csr(destination, name, matrix):
    for suffix in ('data', 'indices', 'indptr'):
        _save_array(destination / f'{name}_{suffix}.npy', getattr(matrix, suffix))



STAGE_NAMES = ['stage_pre.bin', 'stage_post.bin', 'stage_weight.bin']


def _path_inside(destination, name):
    root = Path(destination).resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise ValueError('Index operation escaped destination directory')
    return target


def _annotation_summary(connection):
    counts = dict(neuron=0, glia=0, other=0, unannotated=0)
    for category, count in connection.execute('SELECT category, COUNT(*) FROM nodes WHERE metadata IS NOT NULL GROUP BY category'):
        counts[category] = count
    annotation_ids = np.fromiter((row[0] for row in connection.execute('SELECT bodyId FROM nodes WHERE metadata IS NOT NULL ORDER BY bodyId')), dtype=np.int64)
    row = connection.execute('SELECT metadata FROM nodes WHERE metadata IS NOT NULL LIMIT 1').fetchone()
    fields = list(json.loads(row[0])) if row else ['bodyId']
    return counts, annotation_ids, fields


def _compact_annotations(destination, progress=None):
    """Retain only annotations from legacy interrupted index databases."""
    source = _path_inside(destination, 'annotations.sqlite')
    connection = sqlite3.connect(source)
    try:
        expected = connection.execute('SELECT COUNT(*) FROM nodes WHERE metadata IS NOT NULL').fetchone()[0]
        # EXISTS returns immediately after the first legacy empty annotation.
        needs_compact = connection.execute('SELECT 1 FROM nodes WHERE metadata IS NULL LIMIT 1').fetchone()
        if not needs_compact:
            return
        target = _path_inside(destination, 'annotations.recovery.sqlite')
        if target.exists():
            raise FileExistsError('Partial annotation recovery exists; inspect it before retrying')
        if progress:
            progress({'phase': 'compact_annotations', 'annotated_record_count': expected})
        replacement = sqlite3.connect(target)
        try:
            schema = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='nodes'").fetchone()[0]
            replacement.execute(schema)
            cursor = connection.execute('SELECT * FROM nodes WHERE metadata IS NOT NULL')
            while True:
                block = cursor.fetchmany(1000)
                if not block:
                    break
                replacement.executemany('INSERT INTO nodes VALUES (' + ','.join('?' for _ in block[0]) + ')', block)
                replacement.commit()
            actual = replacement.execute('SELECT COUNT(*) FROM nodes').fetchone()[0]
            if actual != expected:
                raise ValueError('Annotation-only copy row count mismatch')
            for field in FILTER_FIELDS:
                replacement.execute(f'CREATE INDEX "filter_{field}" ON nodes ("{field}")')
            replacement.commit()
        finally:
            replacement.close()
        connection.close()
        connection = None
        # Both exact files are resolved children of the index directory. The
        # verified annotation copy replaces the derived oversized database.
        target.replace(source)
    finally:
        if connection is not None:
            connection.close()


def _unique_staged_ids(staged, annotation_ids, destination, batch_size, progress):
    """Numeric uniqueness only: never construct a Python set of all endpoints."""
    maximum = int(annotation_ids[-1]) if len(annotation_ids) else 0
    for array in staged[:2]:
        maximum = max(maximum, int(array.max()))
    rows = len(staged[0])
    if maximum <= 2 * 1024 ** 3:
        if progress:
            progress({'phase': 'id_bitmap', 'max_body_id': maximum, 'bitmap_bytes': maximum + 1})
        seen = np.zeros(maximum + 1, dtype=np.bool_)
        seen[annotation_ids] = True
        for start in range(0, rows, batch_size):
            seen[staged[0][start:start + batch_size]] = True
            seen[staged[1][start:start + batch_size]] = True
        ids = np.flatnonzero(seen).astype(np.int64, copy=False)
        del seen
        return ids, maximum
    # Sparse very large body IDs (including >2^53) use numeric disk staging;
    # np.unique's work copy is bounded here to <=4 GiB, no Python ID objects.
    elements = rows * 2 + len(annotation_ids)
    if elements * 8 > 4 * 1024 ** 3:
        raise MemoryError('Sparse-ID numeric uniqueness would exceed its 4 GiB work bound')
    unique_path = _path_inside(destination, 'stage_unique.bin')
    combined = np.memmap(unique_path, mode='w+', dtype=np.int64, shape=(elements,))
    combined[:rows], combined[rows:2 * rows], combined[2 * rows:] = staged[0], staged[1], annotation_ids
    combined.flush()
    ids = np.unique(combined)
    combined._mmap.close()
    del combined
    unique_path.unlink()
    return ids, maximum


def _finalize_staging(destination, report, progress=None):
    started = time.perf_counter()
    destination = Path(destination)
    batch_size, rows = int(report['batch_size']), int(report['source_rows'])
    _compact_annotations(destination, progress)
    connection = sqlite3.connect(destination / 'annotations.sqlite')
    try:
        category_counts, annotated_ids, annotation_fields = _annotation_summary(connection)
    finally:
        connection.close()
    staged = [np.memmap(destination / name, mode='r', dtype=np.int64, shape=(rows,)) for name in STAGE_NAMES]
    ids, maximum = _unique_staged_ids(staged, annotated_ids, destination, batch_size, progress)
    annotation_count = len(annotated_ids)
    del annotated_ids
    if len(ids) > np.iinfo(np.int32).max or rows > np.iinfo(np.int32).max:
        raise ValueError('Index v1 requires fewer than 2^31 nodes and source rows')
    remaining_disk = rows * 32 + len(ids) * 40 + (maximum + 1) * 4 if maximum <= 2 * 1024 ** 3 else rows * 32 + len(ids) * 40
    if shutil.disk_usage(destination).free < remaining_disk + 512 * 1024 ** 2:
        raise OSError(f'Insufficient disk for numeric index outputs (estimated {remaining_disk} bytes); staging retained')
    category_counts['unannotated'] = len(ids) - annotation_count
    _save_array(destination / 'ids.npy', ids)
    n = len(ids)
    del ids
    ids = np.load(destination / 'ids.npy', mmap_mode='r')
    # Only compact annotation positions (<=211577) are persisted for fast
    # complement pagination; unknown endpoints never get SQLite rows.
    connection = sqlite3.connect(destination / 'annotations.sqlite')
    try:
        annotation_ids = np.fromiter((row[0] for row in connection.execute('SELECT bodyId FROM nodes ORDER BY bodyId')), dtype=np.int64)
    finally:
        connection.close()
    _save_array(destination / 'annotated_positions.npy', np.searchsorted(ids, annotation_ids).astype(np.int64))
    del annotation_ids
    row = np.memmap(destination / 'stage_row.bin', mode='w+', dtype=np.int32, shape=(rows,))
    col = np.memmap(destination / 'stage_col.bin', mode='w+', dtype=np.int32, shape=(rows,))
    total_input = np.zeros(n, dtype=np.int64)
    total_output = np.zeros(n, dtype=np.int64)
    lookup = None
    if maximum <= 2 * 1024 ** 3:
        lookup = np.memmap(destination / 'stage_lookup.bin', mode='w+', dtype=np.int32, shape=(maximum + 1,))
        for start in range(0, n, batch_size):
            lookup[ids[start:start + batch_size]] = np.arange(start, min(n, start + batch_size), dtype=np.int32)
        if progress:
            progress({'phase': 'dense_id_lookup', 'lookup_bytes': (maximum + 1) * 4, 'node_count': n})
    for start in range(0, rows, batch_size):
        stop = min(rows, start + batch_size)
        if lookup is None:
            pre = np.searchsorted(ids, staged[0][start:stop]).astype(np.int32)
            post = np.searchsorted(ids, staged[1][start:stop]).astype(np.int32)
        else:
            pre, post = lookup[staged[0][start:stop]], lookup[staged[1][start:stop]]
        row[start:stop], col[start:stop] = post, pre
        np.add.at(total_input, post, staged[2][start:stop])
        np.add.at(total_output, pre, staged[2][start:stop])
        if progress and start % (batch_size * 250) == 0:
            progress({'phase': 'map_ids', 'mapped_rows': stop, 'source_rows': rows})
    row.flush()
    col.flush()
    if lookup is not None:
        lookup.flush()
        lookup._mmap.close()
        del lookup
        _path_inside(destination, 'stage_lookup.bin').unlink()
    _save_array(destination / 'total_input.npy', total_input)
    _save_array(destination / 'total_output.npy', total_output)
    if progress:
        progress({'phase': 'incoming_csr', 'source_rows': rows, 'node_count': n})
    incoming = sparse.coo_matrix((staged[2], (row, col)), shape=(n, n), copy=False).tocsr()
    incoming.sum_duplicates()
    incoming.sort_indices()
    edge_count = incoming.nnz
    if not np.array_equal(np.asarray(incoming.sum(axis=1)).ravel(), total_input):
        raise ValueError('Incoming CSR count conservation failed')
    _save_csr(destination, 'incoming', incoming)
    if progress:
        progress({'phase': 'outgoing_csr', 'edge_count': edge_count})
    outgoing = incoming.transpose().tocsr()
    outgoing.sort_indices()
    if not np.array_equal(np.asarray(outgoing.sum(axis=1)).ravel(), total_output):
        raise ValueError('Outgoing CSR count conservation failed')
    _save_csr(destination, 'outgoing', outgoing)
    contacts = int(total_input.sum())
    del incoming, outgoing, pre, post
    row._mmap.close()
    col._mmap.close()
    for array in staged:
        array._mmap.close()
    ids._mmap.close()
    del row, col, staged, ids, array
    gc.collect()
    staging_names=set(STAGE_NAMES + ['stage_row.bin', 'stage_col.bin','staging.json'])
    manifest = {
        'format_version': FORMAT_VERSION, 'index_id': 'malecns-index-' + uuid.uuid4().hex,
        'source_version': 'MaleCNS v1.0 minconf=0.5',
        'source_files': [ANNOTATIONS, WEIGHTS], 'source_url': 'https://male-cns.janelia.org/download/',
        'node_count': n, 'annotated_record_count': annotation_count, 'category_counts': category_counts,
        'category_rule': 'status=Traced: neuron; status=Glia: glia; other annotated records: other; absent annotation: unannotated',
        'source_rows': rows, 'batches': report.get('batches'), 'batch_size': batch_size,
        'edge_count': edge_count, 'duplicate_source_rows': rows - edge_count, 'contacts': contacts,
        'annotation_fields': annotation_fields,
        'orientation': 'incoming: row=post, column=pre; outgoing: row=pre, column=post',
        'normalization': 'Integer full incoming totals retained for every indexed node.',
        'source_scan_seconds': report.get('source_scan_seconds'),
        'build_seconds': round(time.perf_counter() - started + report.get('elapsed_before_finalize', 0), 3),
        'resumed_from_staging': bool(report.get('resumed_from_staging')),
        'index_bytes': sum(path.stat().st_size for path in destination.iterdir() if path.is_file() and path.name not in staging_names),
    }
    pending=_path_inside(destination,'manifest.pending.json')
    pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    pending.replace(_path_inside(destination,'manifest.json'))
    # Commit the complete output before releasing recoverable scan staging.
    for name in STAGE_NAMES + ['stage_row.bin', 'stage_col.bin']:
        _path_inside(destination, name).unlink()
    return manifest


def resume_global_index(destination, expected_rows=None, batch_size=65536, progress=None):
    """Finish an interrupted complete source scan using only local staging.

    Legacy staging without a complete-scan marker requires an explicit expected
    source row count. Equal file lengths alone do not prove a complete scan.
    """
    destination = Path(destination)
    if (destination / 'manifest.json').exists():
        raise FileExistsError('Complete index exists; reuse it')
    marker = destination / 'staging.json'
    report = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
    expected = expected_rows if expected_rows is not None else report.get('source_rows')
    if not isinstance(expected, int) or expected <= 0:
        raise ValueError('Recovery needs explicit expected_rows or a completed staging marker')
    lengths = [(destination / name).stat().st_size for name in STAGE_NAMES]
    if any(length != expected * 8 for length in lengths):
        raise ValueError('Staging files do not match the expected complete source rows')
    report.update(source_rows=expected, batch_size=batch_size, resumed_from_staging=True)
    marker.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return _finalize_staging(destination, report, progress)


def build_global_index(raw, destination, batch_size=65536, progress=None):
    """One Arrow source scan, annotation-only SQLite, numeric disk finalization."""
    raw, destination = Path(raw), Path(destination)
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
        raise ValueError('batch_size must be a positive integer')
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f'Index destination is not empty; reuse it: {destination}')
    started = time.perf_counter()
    destination.mkdir(parents=True, exist_ok=True)
    annotation_source = ds.dataset(raw / ANNOTATIONS, format='ipc')
    fields = sorted(set(FILTER_FIELDS) | (set(annotation_source.schema.names) - {'bodyId', 'category'}))
    if any(not name.replace('_', '').isalnum() for name in fields):
        raise ValueError('Annotation schema has unsupported column identifiers')
    connection = sqlite3.connect(destination / 'annotations.sqlite')
    try:
        connection.execute('CREATE TABLE nodes (bodyId INTEGER PRIMARY KEY, metadata TEXT, ' + ','.join('"' + name + '" TEXT' for name in fields) + ')')
        insert = 'INSERT INTO nodes VALUES (' + ','.join('?' for _ in range(2 + len(fields))) + ')'
        for batch in annotation_source.scanner(batch_size=batch_size, use_threads=False).to_batches():
            records = []
            for annotation in batch.to_pylist():
                annotation = _clean_json(annotation)
                body_id = _body_id(annotation['bodyId'])
                values = dict(annotation, category=_category(annotation))
                values['name'] = annotation.get('name') or annotation.get('instance')
                records.append((body_id, json.dumps(annotation, ensure_ascii=False, allow_nan=False), *(None if values.get(field) is None else str(values[field]) for field in fields)))
            connection.executemany(insert, records)
            connection.commit()
        for field in FILTER_FIELDS:
            connection.execute(f'CREATE INDEX "filter_{field}" ON nodes ("{field}")')
        connection.commit()
    finally:
        connection.close()
    rows, batches = 0, 0
    scanner = ds.dataset(raw / WEIGHTS, format='ipc').scanner(columns=['body_pre', 'body_post', 'weight'], batch_size=batch_size, batch_readahead=1, fragment_readahead=1, use_threads=False)
    handles = [(destination / name).open('wb') for name in STAGE_NAMES]
    scan_started = time.perf_counter()
    try:
        for batch in scanner.to_batches():
            arrays = []
            for name in ('body_pre', 'body_post', 'weight'):
                column = batch.column(batch.schema.get_field_index(name))
                if column.null_count or not pa.types.is_int64(column.type):
                    raise ValueError(f'{name}: expected non-null int64')
                arrays.append(column.to_numpy(zero_copy_only=False))
            if any(np.any(array <= 0) for array in arrays):
                raise ValueError('Body IDs and connection counts must be positive')
            for handle, array in zip(handles, arrays):
                array.tofile(handle)
            rows += batch.num_rows
            batches += 1
            if progress and batches % 100 == 0:
                progress({'phase': 'source_scan', 'source_rows': rows, 'batches': batches, 'elapsed_seconds': round(time.perf_counter() - started, 3)})
            if batches % 100 == 0 and shutil.disk_usage(destination).free < 2 * 1024 ** 3:
                raise OSError('Less than 2 GiB free during staging; partial files retained')
            del arrays, array, column, batch
    finally:
        for handle in handles:
            handle.close()
    if rows <= 0:
        raise ValueError('Weights table contains no connections')
    report = {'source_rows': rows, 'batches': batches, 'batch_size': batch_size, 'source_scan_seconds': round(time.perf_counter() - scan_started, 3), 'elapsed_before_finalize': time.perf_counter() - started}
    (destination / 'staging.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return _finalize_staging(destination, report, progress)


class _Annotations(Mapping):
    def __init__(self, owner):
        self.owner = owner

    def __getitem__(self, key):
        record = self.owner._fetch_metadata(_body_id(key))
        if record is None:
            raise KeyError(key)
        return record

    def __len__(self):
        return self.owner.info['annotated_record_count']

    def __iter__(self):
        connection = self.owner._connect()
        try:
            for row in connection.execute('SELECT bodyId FROM nodes WHERE metadata IS NOT NULL ORDER BY bodyId'):
                yield row[0]
        finally:
            connection.close()


class GlobalIndex:
    def __init__(self, path):
        self.path = Path(path)
        self.info = json.loads((self.path / 'manifest.json').read_text(encoding='utf-8'))
        if self.info.get('format_version') != FORMAT_VERSION:
            raise ValueError('Unsupported global index version')
        self.manifest = self.info
        self.filter_fields = tuple(sorted(set(FILTER_FIELDS) |
                                          (set(self.info.get('annotation_fields', [])) - {'bodyId'})))
        self.ids = np.load(self.path / 'ids.npy', mmap_mode='r')
        self.total_input = np.load(self.path / 'total_input.npy', mmap_mode='r')
        self.total_output = np.load(self.path / 'total_output.npy', mmap_mode='r')
        self.annotated_positions = np.load(self.path / 'annotated_positions.npy', mmap_mode='r')
        n = len(self.ids)
        self._arrays = []
        for name in ('incoming', 'outgoing'):
            data, indices, indptr = [np.load(self.path / f'{name}_{suffix}.npy', mmap_mode='r')
                                    for suffix in ('data', 'indices', 'indptr')]
            self._arrays.extend((data, indices, indptr))
            setattr(self, name, sparse.csr_matrix((data, indices, indptr), shape=(n, n), copy=False))
        self.annotations = _Annotations(self)

    def _connect(self):
        # A fresh readonly connection makes queries safe across HTTP threads.
        return sqlite3.connect((self.path / 'annotations.sqlite').resolve().as_uri() + '?mode=ro', uri=True)

    def _fetch_metadata(self, body_id):
        connection = self._connect()
        try:
            row = connection.execute('SELECT metadata FROM nodes WHERE bodyId=?', (body_id,)).fetchone()
            return json.loads(row[0]) if row and row[0] else None
        finally:
            connection.close()

    def position(self, body_id):
        body_id = _body_id(body_id)
        index = int(np.searchsorted(self.ids, body_id))
        if index == len(self.ids) or self.ids[index] != body_id:
            raise KeyError(f'Unknown global body ID: {body_id}')
        return index

    def node(self, body_id):
        position = self.position(body_id)
        body_id = int(self.ids[position])
        annotation = self._fetch_metadata(body_id)
        return self._node_from_annotation(body_id, position, annotation)

    def _node_from_annotation(self, body_id, position, annotation):
        result = dict(annotation or {})
        result.update(bodyId=str(body_id), category=_category(annotation) if annotation else 'unannotated',
                      total_input=int(self.total_input[position]), total_output=int(self.total_output[position]),
                      incoming_edges=int(self.incoming.indptr[position + 1] - self.incoming.indptr[position]),
                      outgoing_edges=int(self.outgoing.indptr[position + 1] - self.outgoing.indptr[position]))
        return result

    def nodes(self, body_ids):
        """Resolve selected IDs in input order using one SQLite connection.

        SQL batches stay below SQLite's conservative 999-bind limit. Unknown
        annotation endpoints are valid nodes; absent graph IDs raise KeyError.
        """
        body_ids = np.asarray([_body_id(item) for item in body_ids], dtype=np.int64)
        if not len(body_ids):
            return []
        positions = np.searchsorted(self.ids, body_ids)
        if np.any(positions >= len(self.ids)) or np.any(self.ids[np.minimum(positions, len(self.ids) - 1)] != body_ids):
            raise KeyError('Selection contains a body ID outside the global index')
        connection = self._connect()
        records = {}
        try:
            for start in range(0, len(body_ids), 900):
                block = [int(item) for item in body_ids[start:start + 900]]
                placeholders = ','.join('?' for _ in block)
                for body_id, metadata in connection.execute('SELECT bodyId, metadata FROM nodes WHERE bodyId IN (' + placeholders + ')', block):
                    records[body_id] = json.loads(metadata) if metadata else None
        finally:
            connection.close()
        return [self._node_from_annotation(int(body_id), int(position), records.get(int(body_id)))
                for body_id, position in zip(body_ids, positions)]

    def _where(self, filters):
        if not isinstance(filters, dict):
            raise ValueError('filters must be an object')
        if any(key not in self.filter_fields + ('q', 'bodyId') for key in filters):
            raise ValueError('Unsupported annotation filter')
        clauses, params = [], []
        for key, value in filters.items():
            if value is None or value == '':
                continue
            if key == 'q':
                if not isinstance(value, str) or len(value) > 500:
                    raise ValueError('q must be a string of at most 500 characters')
                escaped = '%' + value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                clauses.append("(CAST(bodyId AS TEXT) LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' OR instance LIKE ? ESCAPE '\\' OR type LIKE ? ESCAPE '\\')")
                params.extend([escaped] * 4)
            else:
                values = value if isinstance(value, (list, tuple)) else [value]
                if not values or len(values) > 1000:
                    raise ValueError('Exact filter must contain 1–1000 values')
                if key == 'bodyId':
                    values = [_body_id(item) for item in values]
                elif any(not isinstance(item, str) for item in values):
                    raise ValueError('Annotation filters require text values')
                clauses.append('"' + key + '" IN (' + ','.join('?' for _ in values) + ')')
                params.extend(values)
        return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), params

    def _selection(self, filters):
        """Represent broad endpoint queries by small excluded-position arrays.

        q searches annotated names/types and annotated ID substrings; for an
        unannotated endpoint, q accepts its exact numeric body ID. The bodyId
        filter always performs exact graph-ID lookup, independent of SQLite.
        """
        where, params = self._where(filters)
        active = {key: value for key, value in filters.items() if value is not None and value != ''}
        categories = active.get('category')
        categories = categories if isinstance(categories, (tuple, list)) else [categories]
        unknown_allowed = categories == [None] or 'unannotated' in categories
        annotation_constraints = any(key not in ('bodyId', 'category', 'q') for key in active)
        if not active:
            return 'complement', np.empty(0, dtype=np.int64), len(self.ids)
        if active == {'category': 'unannotated'}:
            return 'complement', self.annotated_positions, len(self.ids) - len(self.annotated_positions)
        connection = self._connect()
        try:
            matches = np.fromiter((record[0] for record in connection.execute('SELECT bodyId FROM nodes' + where + ' ORDER BY bodyId', params)), dtype=np.int64)
        finally:
            connection.close()
        if 'bodyId' in active:
            requested = active['bodyId']
            requested = requested if isinstance(requested, (list, tuple)) else [requested]
            requested = np.unique(np.array([_body_id(item) for item in requested], dtype=np.int64))
            positions = np.searchsorted(self.ids, requested)
            valid = positions < len(self.ids)
            valid &= self.ids[np.minimum(positions, len(self.ids) - 1)] == requested
            requested, positions = requested[valid], positions[valid]
            known = np.isin(positions, self.annotated_positions)
            unknown = requested[~known] if unknown_allowed and not annotation_constraints else np.empty(0, dtype=np.int64)
            if active.get('q'):
                q = active['q']
                unknown = unknown[unknown == int(q)] if q.isdecimal() else np.empty(0, dtype=np.int64)
            result = np.union1d(matches, unknown)
            return 'ids', result, len(result)
        if unknown_allowed and not annotation_constraints and 'q' not in active:
            matched_positions = np.searchsorted(self.ids, matches)
            excluded = np.setdiff1d(self.annotated_positions, matched_positions, assume_unique=True)
            return 'complement', excluded, len(self.ids) - len(excluded)
        q = active.get('q')
        if unknown_allowed and not annotation_constraints and isinstance(q, str) and q.isdecimal():
            try:
                position = self.position(q)
            except (KeyError, ValueError):
                pass
            else:
                if not np.any(self.annotated_positions == position):
                    matches = np.union1d(matches, [int(self.ids[position])])
        return 'ids', matches, len(matches)

    def _selection_page(self, mode, selection, total, offset, limit):
        count = max(0, min(limit, total - offset))
        if mode == 'ids':
            return selection[offset:offset + count]
        if not count:
            return np.empty(0, dtype=np.int64)
        if not len(selection):
            return self.ids[offset:offset + count]
        ranks = np.arange(offset + 1, offset + count + 1, dtype=np.int64)
        low = ranks - 1
        high = np.minimum(ranks + len(selection) - 1, len(self.ids) - 1)
        while np.any(low < high):
            middle = (low + high) // 2
            available = middle + 1 - np.searchsorted(selection, middle, side='right')
            move_high = available >= ranks
            high = np.where(move_high, middle, high)
            low = np.where(move_high, low, middle + 1)
        return self.ids[low]

    def ids_for(self, filters=None, max_count=200000):
        """Return all matching sorted int64 IDs or refuse an exceeded bound.

        This never truncates a saved selection or resolves per-node metadata.
        """
        if not isinstance(max_count, int) or isinstance(max_count, bool) or max_count <= 0:
            raise ValueError('max_count must be a positive integer')
        mode, selection, count = self._selection(filters or {})
        if count > max_count:
            raise ValueError(f'Filter matches {count} nodes, exceeding max_count={max_count}')
        if mode == 'ids':
            return selection
        if not len(selection):
            return np.array(self.ids, dtype=np.int64)
        result = np.empty(count, dtype=np.int64)
        written = 0
        for start in range(0, len(self.ids), 1000000):
            stop = min(len(self.ids), start + 1000000)
            mask = np.ones(stop - start, dtype=np.bool_)
            bounds = np.searchsorted(selection, [start, stop])
            mask[selection[bounds[0]:bounds[1]] - start] = False
            block = self.ids[start:stop][mask]
            result[written:written + len(block)] = block
            written += len(block)
        return result

    def find(self, filters=None, limit=100, offset=0):
        filters = filters or {}
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (limit, offset)) or not 1 <= limit <= 10000 or offset < 0:
            raise ValueError('limit must be 1–10000 and offset nonnegative')
        mode, selection, total = self._selection(filters)
        ids = self._selection_page(mode, selection, total, offset, limit)
        return {'nodes': self.nodes(ids), 'total': total, 'limit': limit, 'offset': offset}

    def neighbors(self, body_id, direction='incoming', limit=100, offset=0):
        if direction not in ('incoming', 'outgoing'):
            raise ValueError('direction must be incoming or outgoing')
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10000:
            raise ValueError('limit must be 1–10000')
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError('offset must be a nonnegative integer')
        position = self.position(body_id)
        matrix = getattr(self, direction)
        start, stop = matrix.indptr[position:position + 2]
        indices, values = matrix.indices[start:stop], matrix.data[start:stop]
        order = np.lexsort((self.ids[indices], -values))[offset:offset + limit]
        nodes = self.nodes(self.ids[indices[order]])
        return {'bodyId': str(_body_id(body_id)), 'direction': direction,
                'nodes': [{'node': node, 'weight': int(values[j])} for node, j in zip(nodes, order)],
                'edge_count': int(stop - start), 'contacts': int(values.sum()), 'limit': limit, 'offset': offset}

    def close(self):
        for array in [self.ids, self.total_input, self.total_output, self.annotated_positions] + self._arrays:
            if getattr(array, '_mmap', None) is not None:
                array._mmap.close()

