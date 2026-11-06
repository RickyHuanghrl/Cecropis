"""Read unsharded Neuroglancer skeletons in model nanometres, without network IO.

The official format stores both counts before positions. Display coordinates are
micrometres; skeleton links remain undirected morphology, not connectome edges.
"""
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import sparse


PARSER_VERSION = "precomputed-nm-um-v1"
DTYPES = {name: np.dtype(code) for name, code in {
    "float32": "<f4", "int8": "i1", "uint8": "u1", "int16": "<i2",
    "uint16": "<u2", "int32": "<i4", "uint32": "<u4"}.items()}


def body_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("body_id must be an exact numeric string or integer")
    value = str(value)
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("body_id must be canonical and positive")
    if int(value) > 2**64 - 1:
        raise ValueError("precomputed segment ID exceeds uint64")
    return value


def metadata(info):
    """Validate metadata; transform is a column-major 3 by 4 matrix."""
    if isinstance(info, (str, Path)):
        info = json.loads(Path(info).read_text(encoding="utf-8"))
    if not isinstance(info, dict) or info.get("@type") != "neuroglancer_skeletons":
        raise ValueError("info.@type must be neuroglancer_skeletons")
    if info.get("sharding") is not None:
        raise ValueError("sharded skeletons are not supported by this local reader")
    transform = np.asarray(info.get("transform", [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]), dtype=np.float64)
    if transform.shape != (12,) or not np.isfinite(transform).all():
        raise ValueError("info.transform must contain twelve finite numbers")
    matrix = transform.reshape((3, 4), order="F")
    if abs(np.linalg.det(matrix[:, :3])) < 1e-15:
        raise ValueError("info.transform is singular")
    attributes, identifiers = [], set()
    for attribute in info.get("vertex_attributes", []):
        identifier = attribute.get("id")
        components = attribute.get("num_components")
        dtype = attribute.get("data_type")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("vertex attribute IDs must be unique nonempty strings")
        if isinstance(components, bool) or not isinstance(components, int) or not 1 <= components <= 64:
            raise ValueError(f"attribute {identifier}: invalid component count")
        if dtype not in DTYPES:
            raise ValueError(f"attribute {identifier}: unsupported data_type")
        if identifier == "radius" and (dtype != "float32" or components != 1):
            raise ValueError("radius must be float32 with one component")
        identifiers.add(identifier)
        attributes.append(dict(id=identifier, data_type=dtype, num_components=components))
    if "radius" in identifiers:
        gram = matrix[:, :3].T @ matrix[:, :3]
        if not np.allclose(gram, np.eye(3) * gram[0, 0], rtol=1e-6, atol=1e-10):
            raise ValueError("radius requires a uniform transform scale")
    return dict(parser_version=PARSER_VERSION, transform=transform.tolist(),
                vertex_attributes=attributes, stored_units="model coordinates",
                model_units="nanometres", display_units="micrometres",
                display_scale=.001, coordinate_space="MaleCNS EM unmirrored")


def rules_id(rules):
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass
class Skeleton:
    body_id: str
    positions: np.ndarray
    edges: np.ndarray
    radii: np.ndarray
    has_radius: bool
    attributes: dict

    @property
    def bounds(self):
        return [self.positions.min(axis=0).tolist(), self.positions.max(axis=0).tolist()]


def parse(data, identifier, info, *, max_vertices=4_000_000, max_edges=4_000_000):
    identifier = body_id(identifier)
    rules = info if isinstance(info, dict) and info.get("parser_version") else metadata(info)
    if len(data) < 8:
        raise ValueError("skeleton header is truncated")
    vertices, edge_count = struct.unpack_from("<II", data)
    if not 1 <= vertices <= max_vertices or edge_count > max_edges:
        raise ValueError(f"skeleton geometry exceeds limits: {vertices} vertices / {edge_count} edges")
    required = 8 + vertices * 12 + edge_count * 8
    for attribute in rules["vertex_attributes"]:
        required += vertices * attribute["num_components"] * DTYPES[attribute["data_type"]].itemsize
    if len(data) != required:
        raise ValueError(f"skeleton structure length mismatch: {len(data)} bytes, expected {required}")
    xyz = np.frombuffer(data, dtype="<f4", count=vertices * 3, offset=8).reshape(vertices, 3)
    if not np.isfinite(xyz).all():
        raise ValueError("skeleton positions contain nonfinite values")
    matrix = np.asarray(rules["transform"], dtype=np.float64).reshape((3, 4), order="F")
    positions = ((xyz.astype(np.float64) @ matrix[:, :3].T + matrix[:, 3]) * .001).astype("<f4")
    if not np.isfinite(positions).all():
        raise ValueError("transformed coordinates exceed float32 display range")
    offset = 8 + vertices * 12
    edges = np.frombuffer(data, dtype="<u4", count=edge_count * 2, offset=offset).reshape(edge_count, 2).copy()
    if edge_count and int(edges.max()) >= vertices:
        raise ValueError("skeleton edge references an absent vertex")
    # Degenerate links are retained in the source detail but ignored by drawing
    # and simplification; they do not establish another branch.
    offset += edge_count * 8
    attributes, radii = {}, np.zeros(vertices, dtype="<f4")
    has_radius = False
    for attribute in rules["vertex_attributes"]:
        count = vertices * attribute["num_components"]
        dtype = DTYPES[attribute["data_type"]]
        values = np.frombuffer(data, dtype=dtype, count=count, offset=offset).reshape(vertices, attribute["num_components"])
        if dtype.kind == "f" and not np.isfinite(values).all():
            raise ValueError(f"attribute {attribute['id']} contains nonfinite values")
        attributes[attribute["id"]] = values.copy()
        if attribute["id"] == "radius":
            if (values < 0).any():
                raise ValueError("radius must be nonnegative")
            scale = float(np.linalg.norm(matrix[:, 0])) * .001
            radii = (values[:, 0] * scale).astype("<f4")
            if not np.isfinite(radii).all():
                raise ValueError("transformed radius exceeds float32 display range")
            has_radius = True
        offset += count * dtype.itemsize
    return Skeleton(identifier, positions, edges, radii, has_radius, attributes)


def pack(skeleton):
    """Display binary: Nv,Ne; xyz[Nv,3]; radius[Nv]; links[Ne,2]."""
    return b"".join([struct.pack("<II", len(skeleton.positions), len(skeleton.edges)),
                     skeleton.positions.astype("<f4", copy=False).tobytes(),
                     skeleton.radii.astype("<f4", copy=False).tobytes(),
                     skeleton.edges.astype("<u4", copy=False).tobytes()])


def unpack(data, identifier):
    if len(data) < 8:
        raise ValueError("cache header is truncated")
    n, e = struct.unpack_from("<II", data)
    if n == 0 or len(data) != 8 + 16 * n + 8 * e:
        raise ValueError("cache length mismatch")
    xyz = np.frombuffer(data, "<f4", n * 3, 8).reshape(n, 3)
    radius = np.frombuffer(data, "<f4", n, 8 + n * 12)
    edges = np.frombuffer(data, "<u4", e * 2, 8 + n * 16).reshape(e, 2)
    if not np.isfinite(xyz).all() or not np.isfinite(radius).all() or (radius < 0).any() or (e and edges.max() >= n):
        raise ValueError("cache arrays are invalid")
    return Skeleton(body_id(identifier), xyz, edges, radius, bool((radius > 0).any()), {})


def chains(skeleton):
    """Split at junctions, retaining degree-two cycles and disconnected vertices.

    Numeric CSR adjacency and edge visitation avoid Python edge dictionaries.
    """
    n = len(skeleton.positions)
    edges = skeleton.edges[skeleton.edges[:, 0] != skeleton.edges[:, 1]]
    if not len(edges):
        return [], np.zeros(n, dtype=np.int64)
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    e = len(edges)
    rows = np.concatenate([edges[:, 0], edges[:, 1]])
    columns = np.concatenate([edges[:, 1], edges[:, 0]])
    identifiers = np.tile(np.arange(e, dtype=np.int64) + 1, 2)
    adjacency = sparse.csr_matrix((identifiers, (rows, columns)), shape=(n, n))
    degree = np.diff(adjacency.indptr)
    visited = np.zeros(e, dtype=bool)
    result = []

    def walk(start, neighbor, edge):
        path = [int(start)]
        current, link = int(neighbor), int(edge)
        while not visited[link]:
            visited[link] = True
            path.append(current)
            if degree[current] != 2 or current == start:
                break
            begin, end = adjacency.indptr[current:current + 2]
            options = adjacency.data[begin:end] - 1
            choices = np.flatnonzero(~visited[options])
            if not len(choices):
                break
            choice = begin + int(choices[0])
            current, link = int(adjacency.indices[choice]), int(adjacency.data[choice] - 1)
        if len(path) > 1:
            result.append(np.asarray(path, dtype=np.uint32))

    for start in np.flatnonzero((degree != 2) & (degree > 0)):
        begin, end = adjacency.indptr[start:start + 2]
        for location in range(begin, end):
            edge = int(adjacency.data[location] - 1)
            if not visited[edge]:
                walk(start, adjacency.indices[location], edge)
    for edge in np.flatnonzero(~visited):
        if not visited[edge]:
            walk(edges[edge, 0], edges[edge, 1], edge)
    return result, degree


def _rdp(points, tolerance):
    keep = np.zeros(len(points), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        segment = points[b] - points[a]
        length2 = float(segment @ segment)
        delta = points[a + 1:b] - points[a]
        if length2:
            projection = np.clip(delta @ segment / length2, 0, 1)
            residual = delta - projection[:, None] * segment
        else:
            residual = delta
        distance2 = np.einsum("ij,ij->i", residual, residual)
        location = int(np.argmax(distance2))
        if float(distance2[location]) > tolerance * tolerance:
            middle = a + 1 + location
            keep[middle] = True
            stack.extend([(a, middle), (middle, b)])
    return np.flatnonzero(keep)


def simplify(skeleton, tolerance, prepared=None):
    if tolerance <= 0:
        return skeleton
    paths, degree = prepared if prepared is not None else chains(skeleton)
    links = []
    selected = set(map(int, np.flatnonzero(degree == 0)))
    for path in paths:
        # A cycle keeps three original anchors, so collapsing a nearly circular
        # or zero-length chain cannot turn the cycle into a self edge.
        if path[0] == path[-1] and len(path) >= 4:
            anchors = sorted({0, (len(path) - 1) // 3, 2 * (len(path) - 1) // 3, len(path) - 1})
            retained = []
            for a, b in zip(anchors[:-1], anchors[1:]):
                retained.extend((a + _rdp(skeleton.positions[path[a:b + 1]], tolerance)).tolist())
            retained = np.unique(retained)
        else:
            retained = _rdp(skeleton.positions[path], tolerance)
        members = path[retained]
        selected.update(map(int, members))
        links.extend(zip(map(int, members[:-1]), map(int, members[1:])))
    members = np.asarray(sorted(selected), dtype=np.uint32)
    mapping = np.full(len(skeleton.positions), -1, dtype=np.int64)
    mapping[members] = np.arange(len(members))
    edges = mapping[np.asarray(links, dtype=np.uint32).reshape(-1, 2)].astype("<u4")
    return Skeleton(skeleton.body_id, skeleton.positions[members], edges,
                    skeleton.radii[members], skeleton.has_radius, {})
