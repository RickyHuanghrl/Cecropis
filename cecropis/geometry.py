"""Local MaleCNS EM-space SWC ingestion; no network or generated geometry."""
import math
import re
from pathlib import Path


EM_TO_UM = .008
MAX_POINTS = 200_000
MAX_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 4096


def _body_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('Expected a canonical numeric body ID')
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]*', value):
        raise ValueError('Expected a canonical numeric body ID')
    return value


class GeometryStore:
    """Read only known case IDs from ``directory/<bodyId>.swc``.

    Files must be official, unmirrored MaleCNS EM-space SWC (8 nm units).
    Units are converted to micrometres without rotation or translation.
    Overview positions are skeleton centroids, not inferred soma positions.
    """

    def __init__(self, case, directory, *, max_points=MAX_POINTS, max_bytes=MAX_BYTES):
        for name, value, maximum in [('max_points', max_points, MAX_POINTS),
                                     ('max_bytes', max_bytes, MAX_BYTES)]:
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f'{name} must be an integer in [1, {maximum}]')
        self.directory = Path(directory).resolve()
        self.nodes = {_body_id(node['bodyId']): node for node in case['nodes']}
        self.max_points = max_points
        self.max_bytes = max_bytes

    def _path(self, body_id):
        path = (self.directory / f'{body_id}.swc').resolve()
        if path.parent != self.directory:
            raise ValueError(f'Body {body_id}: geometry path escapes its directory')
        return path

    def skeleton(self, body_id):
        body_id = _body_id(body_id)
        if body_id not in self.nodes:
            raise ValueError(f'Body {body_id}: not in the current case')
        try:
            return self._read(self._path(body_id), body_id)
        except (OSError, UnicodeError, ValueError) as error:
            raise ValueError(f'Body {body_id}: {error}') from error

    def _read(self, path, body_id):
        if not path.is_file():
            raise ValueError('local SWC is missing')
        if path.stat().st_size > self.max_bytes:
            raise ValueError('SWC byte limit exceeded')
        point_ids, points, radii, types, parents = [], [], [], [], []
        indices = {}
        consumed = 0
        with path.open('rb') as stream:
            line_number = 0
            while True:
                raw = stream.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    break
                line_number += 1
                consumed += len(raw)
                if len(raw) > MAX_LINE_BYTES:
                    raise ValueError(f'line {line_number}: line byte limit exceeded')
                if consumed > self.max_bytes:
                    raise ValueError('SWC byte limit exceeded')
                line = raw.decode('utf-8-sig').split('#', 1)[0].strip()
                if not line:
                    continue
                if len(points) >= self.max_points:
                    raise ValueError('SWC point limit exceeded')
                fields = line.split()
                if len(fields) != 7:
                    raise ValueError(f'line {line_number}: expected seven SWC fields')
                try:
                    point_id, kind, parent = int(fields[0]), int(fields[1]), int(fields[6])
                    x, y, z, radius = map(float, fields[2:6])
                except ValueError as error:
                    raise ValueError(f'line {line_number}: invalid numeric SWC field') from error
                if point_id <= 0 or point_id in indices:
                    raise ValueError(f'line {line_number}: point ID must be unique and positive')
                if kind < 0 or parent < -1 or parent == 0 or parent == point_id:
                    raise ValueError(f'line {line_number}: invalid type or parent')
                if not all(math.isfinite(v) for v in [x, y, z, radius]) or radius < 0:
                    raise ValueError(f'line {line_number}: coordinates/radius must be finite; radius nonnegative')
                indices[point_id] = len(points)
                point_ids.append(point_id)
                points.append([x * EM_TO_UM, y * EM_TO_UM, z * EM_TO_UM])
                radii.append(radius * EM_TO_UM)
                types.append(kind)
                parents.append(parent)
        if not points:
            raise ValueError('SWC has no points')
        edges = []
        parent_indices = []
        for index, parent in enumerate(parents):
            if parent == -1:
                parent_indices.append(-1)
            elif parent not in indices:
                raise ValueError(f'point {point_ids[index]}: dangling parent {parent}')
            else:
                parent_indices.append(indices[parent])
                edges.append([index, indices[parent]])
        # Iterative forest validation avoids recursion on long neurites.
        colors = bytearray(len(points))
        for start in range(len(points)):
            if colors[start]:
                continue
            chain = []
            current = start
            while current != -1 and colors[current] == 0:
                colors[current] = 1
                chain.append(current)
                current = parent_indices[current]
            if current != -1 and colors[current] == 1:
                raise ValueError(f'point {point_ids[current]}: parent cycle')
            for index in chain:
                colors[index] = 2
        bounds = [[min(p[d] for p in points) for d in range(3)],
                  [max(p[d] for p in points) for d in range(3)]]
        position = [math.fsum(p[d] / len(points) for p in points) for d in range(3)]
        node = self.nodes[body_id]
        return {'bodyId': body_id, 'type': node.get('type'), 'role': node.get('role'),
                'coordinate_space': 'male-cns-em', 'units': 'um',
                'source_units_nm': 8, 'position_kind': 'skeleton-centroid',
                'position': position, 'bounds': bounds, 'point_count': len(points),
                'point_ids': point_ids, 'points': points, 'edges': edges,
                'radii': radii, 'swc_types': types}

    def overview(self):
        nodes, errors = [], []
        missing = 0
        for body_id in sorted(self.nodes, key=int):
            try:
                path = self._path(body_id)
                if not path.is_file():
                    missing += 1
                    continue
                geometry = self.skeleton(body_id)
                nodes.append({key: geometry[key] for key in
                              ['bodyId', 'type', 'role', 'position', 'position_kind', 'bounds', 'point_count']})
            except ValueError as error:
                errors.append({'bodyId': body_id, 'error': str(error)})
        return {'coordinate_space': 'male-cns-em', 'units': 'um',
                'position_kind': 'skeleton-centroid', 'nodes': nodes,
                'available_count': len(nodes), 'missing_count': missing,
                'invalid_count': len(errors), 'case_node_count': len(self.nodes), 'errors': errors}
