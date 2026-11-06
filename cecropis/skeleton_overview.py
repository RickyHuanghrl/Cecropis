"""Continuous principal paths from actual morphology; no connectome inference.

Existing Numba accelerates bounded forest walks. No compiled files are cached in
the environment. Overview may omit minor branches; full detail remains separate.
"""
import struct
import numpy as np
from numba import njit
from scipy import sparse


@njit(cache=False)
def _principal(indptr, indices, xyz, branches):
    n = len(xyz)
    seen = np.zeros(n, np.uint8)
    stack = np.empty(n, np.int64)
    parent = np.full(n, -1, np.int64)
    distance = np.zeros(n, np.float64)
    components = []
    # Each second walk yields a continuous long path within one component.
    for root in range(n):
        if seen[root]:
            continue
        size = 1
        stack[0] = root
        seen[root] = 1
        farthest = root
        members = []
        while size:
            size -= 1
            a = stack[size]
            members.append(a)
            if distance[a] > distance[farthest]:
                farthest = a
            for k in range(indptr[a], indptr[a + 1]):
                b = indices[k]
                if not seen[b]:
                    seen[b] = 1
                    parent[b] = a
                    distance[b] = distance[a] + np.sqrt(np.sum((xyz[b] - xyz[a]) ** 2))
                    stack[size] = b
                    size += 1
        for a in members:
            seen[a] = 2
            parent[a] = -1
            distance[a] = 0
        size = 1
        stack[0] = farthest
        seen[farthest] = 3
        end = farthest
        while size:
            size -= 1
            a = stack[size]
            if distance[a] > distance[end]:
                end = a
            for k in range(indptr[a], indptr[a + 1]):
                b = indices[k]
                if seen[b] == 2:
                    seen[b] = 3
                    parent[b] = a
                    distance[b] = distance[a] + np.sqrt(np.sum((xyz[b] - xyz[a]) ** 2))
                    stack[size] = b
                    size += 1
        path = []
        current = end
        while current != -1:
            path.append(current)
            current = parent[current]
        components.append((distance[end], path))
    # Keep largest components, never connect disconnected morphology.
    components.sort(key=lambda item: item[0], reverse=True)
    paths = []
    selected = np.zeros(n, np.uint8)
    for k in range(min(3, len(components))):
        path = components[k][1]
        paths.append(np.asarray(path, np.int64))
        for a in path:
            selected[a] = 1
    queue = np.empty(n, np.int64)
    for _ in range(branches):
        head = 0
        tail = 0
        seen[:] = 0
        distance[:] = 0
        parent[:] = -1
        for a in range(n):
            if selected[a]:
                queue[tail] = a
                tail += 1
                seen[a] = 1
        farthest = -1
        while head < tail:
            a = queue[head]
            head += 1
            for k in range(indptr[a], indptr[a + 1]):
                b = indices[k]
                if not seen[b]:
                    seen[b] = 1
                    parent[b] = a
                    distance[b] = distance[a] + np.sqrt(np.sum((xyz[b] - xyz[a]) ** 2))
                    queue[tail] = b
                    tail += 1
                    if farthest < 0 or distance[b] > distance[farthest]:
                        farthest = b
        if farthest < 0 or distance[farthest] <= 0:
            break
        path = [farthest]
        current = farthest
        while not selected[current] and parent[current] >= 0:
            selected[current] = 1
            current = parent[current]
            path.append(current)
        paths.append(np.asarray(path, np.int64))
    return paths


@njit(cache=False)
def _simplified_indices(points, tolerance):
    n = len(points)
    keep = np.zeros(n, np.uint8)
    keep[0] = keep[n - 1] = 1
    starts = np.empty(n, np.int64)
    stops = np.empty(n, np.int64)
    starts[0], stops[0] = 0, n - 1
    top = 1
    while top:
        top -= 1
        a, b = starts[top], stops[top]
        dx, dy, dz = points[b] - points[a]
        norm = dx * dx + dy * dy + dz * dz
        maximum, middle = tolerance * tolerance, -1
        for k in range(a + 1, b):
            x, y, z = points[k] - points[a]
            t = max(0., min(1., (x * dx + y * dy + z * dz) / norm)) if norm else 0.
            value = (x - t * dx) ** 2 + (y - t * dy) ** 2 + (z - t * dz) ** 2
            if value > maximum:
                maximum, middle = value, k
        if middle >= 0:
            keep[middle] = 1
            starts[top], stops[top] = a, middle
            starts[top + 1], stops[top + 1] = middle, b
            top += 2
    return np.flatnonzero(keep)


def principal_paths(skeleton, tolerance=16., max_segments=48):
    n = len(skeleton.positions)
    edges = skeleton.edges
    if len(edges):
        rows = np.concatenate((edges[:, 0], edges[:, 1]))
        columns = np.concatenate((edges[:, 1], edges[:, 0]))
        adjacency = sparse.csr_matrix((np.ones(len(rows), np.uint8), (rows, columns)), shape=(n, n))
        adjacency.sort_indices()
        paths = _principal(adjacency.indptr, adjacency.indices, skeleton.positions, 3)
    else:
        paths = [np.asarray([i]) for i in range(min(3, n))]
    # Keep attachments even when a main path is simplified past its junction.
    anchors = {int(p[0]) for p in paths} | {int(p[-1]) for p in paths}
    original = []
    for path in paths:
        cuts = [i for i, vertex in enumerate(path) if int(vertex) in anchors]
        if len(path) == 1:
            original.append(skeleton.positions[path])
        else:
            for a, b in zip(cuts[:-1], cuts[1:]):
                original.append(skeleton.positions[path[a:b + 1]])
    for _ in range(14):
        reduced = [p[_simplified_indices(p, tolerance)] for p in original]
        if sum(max(0, len(p) - 1) for p in reduced) <= max_segments:
            break
        tolerance *= 1.6
    return reduced, float(tolerance)


def encode_paths(paths):
    lengths = np.asarray([len(p) for p in paths], '<u4')
    xyz = np.concatenate(paths).astype('<f4') if paths else np.empty((0, 3), '<f4')
    return struct.pack('<I', len(paths)) + lengths.tobytes() + xyz.tobytes()


def decode_paths(data):
    count = struct.unpack_from('<I', data)[0]
    lengths = np.frombuffer(data, '<u4', count, 4)
    xyz = np.frombuffer(data, '<f4', offset=4 + count * 4).reshape(-1, 3)
    if sum(map(int, lengths)) != len(xyz):
        raise ValueError('overview path structure mismatch')
    paths, offset = [], 0
    for length in lengths:
        paths.append(xyz[offset:offset + int(length)])
        offset += int(length)
    return paths


def path_segments(paths, tolerance=None):
    result = []
    for path in paths:
        if tolerance is not None and len(path) > 2:
            path = path[_simplified_indices(path, tolerance)]
        if len(path) > 1:
            result.append(np.stack((path[:-1], path[1:]), axis=1).reshape(-1, 6))
    return np.concatenate(result).astype('<f4') if result else np.empty((0, 6), '<f4')
