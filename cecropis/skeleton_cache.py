"""Incremental, atomically published local morphology cache.

Raw skeletons and downloader control files are read-only. A fixed directory
snapshot is consumed per explicit prepare; ordinary browsing reads this cache.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import time
import uuid

import numpy as np

from .precomputed import body_id, chains, metadata, pack, parse, rules_id, simplify


CACHE_VERSION = "skeleton-lod-v1"
LOD_TOLERANCES = (0., 1., 4., 16.)
MAX_FILE_BYTES = 128 * 1024**2
DEFAULT_BATCH_BYTES = 512 * 1024**2
MAX_BATCH_BYTES = 16 * 1024**3
TILE_UM = 100.


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _cancelled(cancel):
    return bool(cancel and (cancel() if callable(cancel) else cancel.is_set()))


def _positive(value, field, maximum, optional=False):
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{field} must be an integer in [1, {maximum}]")
    return value


class SkeletonCache:
    def __init__(self, source_root, cache_root=None, index_id=None, annotation_ids=None):
        self.source_root = Path(source_root).resolve()
        default = self.source_root.parent.parent / "geometry-cache" / "precomputed"
        self.cache_root = Path(cache_root or default).resolve()
        if self.cache_root == self.source_root or self.source_root in self.cache_root.parents:
            raise ValueError("geometry cache must be outside the read-only skeleton directory")
        control = self.source_root.parent / (self.source_root.name + ".download")
        if self.cache_root == control or control in self.cache_root.parents:
            raise ValueError("geometry cache must not use downloader control files")
        self.index_id = index_id
        self.annotation_ids = None if annotation_ids is None else {str(x) for x in annotation_ids}
        self.database = self.cache_root / "catalog.sqlite3"
        self.control_root = control

    def _connect(self, write=False):
        if not write and not self.database.is_file():
            return None
        if write:
            self.cache_root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database if write else self.database.as_uri() + "?mode=ro",
                                     uri=not write, timeout=15)
        connection.row_factory = sqlite3.Row
        if write:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bodies (
                    body_id TEXT PRIMARY KEY, source_size INTEGER NOT NULL,
                    source_mtime INTEGER NOT NULL, source_generation TEXT,
                    status TEXT NOT NULL, data TEXT NOT NULL, representatives BLOB);
                CREATE TABLE IF NOT EXISTS expected (
                    body_id TEXT PRIMARY KEY, bytes INTEGER NOT NULL, generation TEXT);
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(expected)")}
            if "downloaded" not in columns:
                connection.execute("ALTER TABLE expected ADD COLUMN downloaded INTEGER NOT NULL DEFAULT 0")
        return connection

    @staticmethod
    def _meta(connection):
        return {row["key"]: json.loads(row["value"]) for row in connection.execute("SELECT * FROM metadata")}

    @staticmethod
    def _set_meta(connection, values):
        connection.executemany("INSERT OR REPLACE INTO metadata VALUES (?,?)",
                               [(key, json.dumps(value, separators=(",", ":"))) for key, value in values.items()])

    def snapshot(self):
        """Read final names and cached official sizes once, never partial payloads."""
        info_path = self.source_root / "info"
        if not info_path.is_file():
            raise ValueError(f"Completed skeleton info is not available: {info_path}")
        rules = metadata(info_path)
        expected = {}
        pages = sorted(self.control_root.glob("listing-*.json"))
        if not pages:
            raise ValueError(f"Official size manifest is missing: {self.control_root}/listing-*.json")
        listing_complete = False
        for number, path in enumerate(pages):
            if path.name != f"listing-{number:04d}.json":
                raise ValueError("Official size listing has a missing page; finish listing before geometry preparation")
            page = json.loads(path.read_text(encoding="utf-8"))
            for item in page.get("items", []):
                name = item["name"].rsplit("/", 1)[-1]
                if name == "info":
                    if info_path.stat().st_size != int(item["size"]):
                        raise ValueError("Completed info length does not match official listing")
                    continue
                if not re.fullmatch(r"[1-9][0-9]*", name):
                    raise ValueError(f"Unexpected skeleton name in official manifest: {name}")
                if name in expected:
                    raise ValueError(f"Duplicate skeleton ID in official listing: {name}")
                expected[name] = dict(body_id=name, expected_bytes=int(item["size"]),
                                      generation=str(item.get("generation", "")))
            listing_complete = not bool(page.get("nextPageToken"))
        if not listing_complete:
            raise ValueError("Official size listing is incomplete; no geometry input snapshot was published")
        available, length_errors, unknown = [], [], []
        with os.scandir(self.source_root) as files:
            for entry in files:
                if not re.fullmatch(r"[1-9][0-9]*", entry.name) or not entry.is_file(follow_symlinks=False):
                    continue
                listed = expected.get(entry.name)
                if listed is None:
                    unknown.append(entry.name)
                    continue
                stat = entry.stat(follow_symlinks=False)
                row = dict(listed, bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
                if stat.st_size != listed["expected_bytes"]:
                    length_errors.append(dict(row, error="final file length differs from official manifest"))
                else:
                    available.append(row)
        available.sort(key=lambda row: int(row["body_id"]))
        identity = rules_id(dict(cache_version=CACHE_VERSION, rules=rules,
                                 tolerances_um=LOD_TOLERANCES, source=str(self.source_root), index_id=self.index_id))
        snapshot_id = hashlib.sha256(json.dumps(available, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return dict(snapshot_id=snapshot_id, cache_id="skeleton-" + identity[:24],
                    coordinate_rule=dict(space="male-cns-em", unit="um", **rules),
                    rules=rules, expected=expected, files=available,
                    length_errors=length_errors, unlisted_final_ids=unknown,
                    expected_count=len(expected), downloaded_count=len(available),
                    pending_count=len(expected) - len(available) - len(length_errors),
                    created=time.time())

    def _entry(self, row):
        value = json.loads(row["data"])
        value.update(body_id=row["body_id"], status=row["status"],
                     source_size=row["source_size"], source_mtime_ns=row["source_mtime"])
        return value

    def overview(self, limit=2000, offset=0):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 5000:
            raise ValueError("limit must be an integer in [0,5000]")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        connection = self._connect()
        if connection is None:
            return dict(status="unprepared", cache_id=None, index_id=self.index_id,
                        coordinate_rule=None, entries=[], entry_count=0,
                        coverage=dict(processed=0, valid=0, invalid=0), limit=limit, offset=offset)
        try:
            meta = self._meta(connection)
            if meta.get("index_id") != self.index_id:
                raise ValueError("Geometry cache index identity differs from the current workspace")
            self._check_source(meta)
            counts = dict(connection.execute("SELECT status,count(*) FROM bodies GROUP BY status").fetchall())
            total = counts.get("available", 0)
            entries = [self._entry(row) for row in connection.execute(
                "SELECT * FROM bodies WHERE status='available' ORDER BY length(body_id),body_id LIMIT ? OFFSET ?", (limit, offset))]
            coverage = dict(meta.get("snapshot_coverage", {}), processed=total,
                            valid=total, invalid=counts.get("invalid", 0))
            stats = connection.execute("SELECT SUM(json_extract(data,'$.cache_bytes')), SUM(json_extract(data,'$.vertices')), SUM(json_extract(data,'$.edges')), SUM(CASE WHEN json_extract(data,'$.annotated')=0 THEN 1 ELSE 0 END) FROM bodies WHERE status='available'").fetchone()
            coverage.update(cache_bytes=int(stats[0] or 0), vertices=int(stats[1] or 0),
                            edges=int(stats[2] or 0), unannotated=int(stats[3] or 0))
            status = meta.get("status", "ready")
            if status == "preparing" and not self._processor_busy():
                status = "interrupted"
            return dict(status=status, cache_id=meta.get("cache_id"),
                        index_id=meta.get("index_id"), coordinate_rule=meta.get("coordinate_rule"),
                        cache_version=CACHE_VERSION, tolerances_um=list(LOD_TOLERANCES),
                        coverage=coverage, snapshot_id=meta.get("snapshot_id"),
                        entries=entries, entry_count=total, limit=limit, offset=offset,
                        has_more=offset + len(entries) < total, processing=meta.get("processing", {}))
        finally:
            connection.close()

    def locate(self, identifiers):
        if not isinstance(identifiers, (list, tuple)) or len(identifiers) > 20000:
            raise ValueError("locate requires at most 20000 exact body IDs")
        identifiers = list(dict.fromkeys(body_id(value) for value in identifiers))
        connection = self._connect()
        if connection is None:
            return dict(cache_id=None, nodes=[dict(body_id=value, status="unprepared") for value in identifiers])
        try:
            meta = self._meta(connection)
            if meta.get("index_id") != self.index_id:
                raise ValueError("Geometry cache index identity mismatch")
            self._check_source(meta)
            rows = []
            for identifier in identifiers:
                row = connection.execute("SELECT * FROM bodies WHERE body_id=?", (identifier,)).fetchone()
                if row:
                    rows.append(self._entry(row))
                else:
                    expected = connection.execute("SELECT * FROM expected WHERE body_id=?", (identifier,)).fetchone()
                    downloaded = bool(expected and "downloaded" in expected.keys() and expected["downloaded"])
                    rows.append(dict(body_id=identifier, status=("downloaded_unprocessed" if downloaded else "not_downloaded") if expected else "missing",
                                     expected_bytes=expected["bytes"] if expected else None))
            return dict(cache_id=meta.get("cache_id"), coordinate_rule=meta.get("coordinate_rule"), nodes=rows)
        finally:
            connection.close()

    def detail(self, identifier, level=0, cache_id=None):
        identifier = body_id(identifier)
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level < len(LOD_TOLERANCES):
            raise ValueError("level must be 0, 1, 2 or 3")
        connection = self._connect()
        if connection is None:
            raise ValueError("Geometry cache has not been prepared")
        try:
            meta = self._meta(connection)
            self._check_source(meta)
            if meta.get("index_id") != self.index_id or (cache_id and cache_id != meta.get("cache_id")):
                raise ValueError("Geometry cache identity no longer matches the requested scene")
            row = connection.execute("SELECT * FROM bodies WHERE body_id=?", (identifier,)).fetchone()
            if row is None or row["status"] != "available":
                raise ValueError(f"Body {identifier}: no published skeleton cache")
            entry = self._entry(row)
            lod = entry["lods"][level]
            path = (self.cache_root / lod["path"]).resolve()
            if self.cache_root not in path.parents:
                raise ValueError("Invalid geometry cache path")
            if path.stat().st_size != lod["bytes"]:
                raise ValueError(f"Body {identifier}: cache length mismatch")
            return path.read_bytes()
        finally:
            connection.close()

    @staticmethod
    def _representatives(skeleton):
        edges = skeleton.edges
        if not len(edges):
            return b""
        endpoints = skeleton.positions[edges]
        length2 = np.einsum("ij,ij->i", endpoints[:, 1] - endpoints[:, 0], endpoints[:, 1] - endpoints[:, 0])
        valid = np.flatnonzero(length2 > 0)
        if not len(valid):
            return b""
        longest = int(valid[np.argmax(length2[valid])])
        choices = [longest]
        centers = endpoints.mean(axis=1)
        for axis in range(3):
            choices.append(int(valid[np.argmax(np.abs(centers[valid, axis] - centers[longest, axis]))]))
        choices = list(dict.fromkeys(choices))
        return endpoints[choices].astype("<f4", copy=False).reshape(-1, 6).tobytes()

    def background_bytes(self, max_edges=300000):
        _positive(max_edges, "max_edges", 2_000_000)
        connection = self._connect()
        if connection is None:
            return struct.pack("<II", 0, 0), dict(cache_id=None, body_count=0, drawn_bodies=0, segment_count=0, bytes=8)
        try:
            meta = self._meta(connection)
            self._check_source(meta)
            if meta.get("index_id") != self.index_id:
                raise ValueError("Geometry cache index identity mismatch")
            count = connection.execute("SELECT count(*) FROM bodies WHERE status='available' AND length(representatives)>0").fetchone()[0]
            if count > max_edges:
                raise ValueError(f"Background budget {max_edges} is below {count} drawable skeletons; increase budget to retain all geometry bodies")
            # At least one real segment for every drawable body. Remaining slots
            # are shared by deterministic hash rank, rather than file-list prefix.
            rows = connection.execute("SELECT body_id,representatives FROM bodies WHERE status='available' AND length(representatives)>0").fetchall()
            rows.sort(key=lambda row: hashlib.blake2b(row["body_id"].encode(), digest_size=8).digest())
            positions, identifiers = [], []
            quota = max_edges // max(1, count)
            spare = max_edges - quota * count
            for i, row in enumerate(rows):
                segments = np.frombuffer(row["representatives"], dtype="<f4").reshape(-1, 6)
                n = min(len(segments), quota + (i < spare))
                positions.append(segments[:n])
                identifiers.extend([int(row["body_id"])] * n)
            xyz = np.concatenate(positions) if positions else np.zeros((0, 6), dtype="<f4")
            ids = np.asarray(identifiers, dtype="<u8")
            data = struct.pack("<II", len(ids), 0) + xyz.tobytes() + ids.tobytes()
            return data, dict(cache_id=meta.get("cache_id"), coordinate_rule=meta.get("coordinate_rule"),
                              body_count=count, drawn_bodies=count, segment_count=len(ids),
                              bytes=len(data), representative=True, per_body_max_segments=4)
        finally:
            connection.close()

    def _check_source(self, meta):
        if meta.get("source_root"):
            if meta["source_root"] != str(self.source_root):
                raise ValueError("Geometry cache belongs to a different raw geometry directory")
            return
        rule = meta.get("coordinate_rule")
        if rule:
            rules = {key: value for key, value in rule.items() if key not in ("space", "unit")}
            identity = rules_id(dict(cache_version=CACHE_VERSION, rules=rules,
                                     tolerances_um=LOD_TOLERANCES, source=str(self.source_root), index_id=self.index_id))
            if meta.get("cache_id") != "skeleton-" + identity[:24]:
                raise ValueError("Geometry cache belongs to a different source or processing rule")

    def _processor_busy(self):
        from .local_tasks import LocalSlot
        if not (self.cache_root / "skeleton-process.lock").exists():
            return False
        try:
            with LocalSlot(self.cache_root, name="skeleton-process.lock"):
                return False
        except ValueError:
            return True

    def prepare(self, max_files=None, max_bytes=DEFAULT_BATCH_BYTES, cancel=None, progress=None,
                max_cache_bytes=16 * 1024**3):
        from .local_tasks import LocalSlot
        with LocalSlot(self.cache_root, name="skeleton-process.lock"):
            return self._prepare(max_files, max_bytes, cancel, progress, max_cache_bytes)

    def _prepare(self, max_files, max_bytes, cancel, progress, max_cache_bytes):
        _positive(max_files, "max_files", 1_000_000, optional=True)
        _positive(max_bytes, "max_bytes", MAX_BATCH_BYTES)
        _positive(max_cache_bytes, "max_cache_bytes", 128 * 1024**3)
        snapshot = self.snapshot()
        connection = self._connect(write=True)
        started = time.perf_counter()
        processed, reused, invalid, consumed, attempted = 0, 0, 0, 0, 0
        status = "completed"
        try:
            prior = self._meta(connection)
            if prior.get("cache_id") and prior["cache_id"] != snapshot["cache_id"]:
                raise ValueError("Cache source, processing rules or index changed; use a separate cache directory")
            downloaded = {item["body_id"] for item in snapshot["files"]}
            downloaded.update(item["body_id"] for item in snapshot["length_errors"])
            connection.executemany("INSERT OR REPLACE INTO expected VALUES (?,?,?,?)",
                                   [(identifier, item["expected_bytes"], item["generation"], identifier in downloaded) for identifier, item in snapshot["expected"].items()])
            coverage = dict(expected=snapshot["expected_count"], downloaded=snapshot["downloaded_count"],
                            pending_download=snapshot["pending_count"], invalid_length=len(snapshot["length_errors"]),
                            unlisted_final=len(snapshot["unlisted_final_ids"]))
            self._set_meta(connection, dict(cache_id=snapshot["cache_id"], index_id=self.index_id,
                                           coordinate_rule=snapshot["coordinate_rule"],
                                           source_root=str(self.source_root),
                                           snapshot_id=snapshot["snapshot_id"], snapshot_coverage=coverage,
                                           status="preparing", snapshot_created=snapshot["created"]))
            for row in snapshot["length_errors"]:
                connection.execute("INSERT OR REPLACE INTO bodies VALUES (?,?,?,?,?,?,?)", (
                    row["body_id"], row["bytes"], row["mtime_ns"], row["generation"], "invalid",
                    json.dumps(dict(error=row["error"])), None))
            connection.commit()
            cache_used = int(connection.execute("SELECT SUM(json_extract(data,'$.cache_bytes')) FROM bodies WHERE status='available'").fetchone()[0] or 0)
            for position, item in enumerate(snapshot["files"]):
                if _cancelled(cancel):
                    status = "cancelled"
                    break
                identifier = item["body_id"]
                old = connection.execute("SELECT * FROM bodies WHERE body_id=?", (identifier,)).fetchone()
                if old and old["source_size"] == item["bytes"] and old["source_mtime"] == item["mtime_ns"] and old["source_generation"] == item["generation"]:
                    if old["status"] == "available":
                        reused += 1
                    else:
                        invalid += 1
                    continue
                if (max_files is not None and attempted >= max_files) or consumed + item["bytes"] > max_bytes:
                    status = "budget_exhausted"
                    break
                attempted += 1
                if item["bytes"] > MAX_FILE_BYTES:
                    error = f"Skeleton file exceeds {MAX_FILE_BYTES} byte per-file limit"
                    skeleton = None
                else:
                    try:
                        path = self.source_root / identifier
                        current = path.stat()
                        if current.st_size != item["bytes"] or current.st_mtime_ns != item["mtime_ns"]:
                            raise ValueError("Completed source changed after the fixed input snapshot")
                        payload = path.read_bytes()
                        skeleton = parse(payload, identifier, snapshot["rules"])
                        after = path.stat()
                        if after.st_size != item["bytes"] or after.st_mtime_ns != item["mtime_ns"]:
                            raise ValueError("Completed source changed during parsing")
                        error = None
                    except (ValueError, OSError) as exception:
                        skeleton, error = None, str(exception)
                consumed += item["bytes"]
                if skeleton is None:
                    invalid += 1
                    connection.execute("INSERT OR REPLACE INTO bodies VALUES (?,?,?,?,?,?,?)", (
                        identifier, item["bytes"], item["mtime_ns"], item["generation"], "invalid",
                        json.dumps(dict(error=error)), None))
                    connection.commit()
                    continue
                prepared = chains(skeleton)
                token = hashlib.sha256(f"{identifier}:{item['bytes']}:{item['mtime_ns']}:{snapshot['cache_id']}".encode()).hexdigest()[:16]
                lods, cache_bytes, pending_files = [], 0, []
                for level, tolerance in enumerate(LOD_TOLERANCES):
                    geometry = simplify(skeleton, tolerance, prepared)
                    data = pack(geometry)
                    relative = f"bodies/{int(identifier) % 256:02x}/{identifier}-{token}-l{level}.bin"
                    pending_files.append((relative, data))
                    cache_bytes += len(data)
                    lods.append(dict(level=level, tolerance_um=tolerance,
                                     vertices=len(geometry.positions), edges=len(geometry.edges),
                                     bytes=len(data), path=relative))
                stored_attributes = []
                # Attributes not used by the renderer stay associated with the
                # full original vertex ordering, rather than being silently lost.
                for attribute_number, (name, values) in enumerate(skeleton.attributes.items()):
                    relative = f"bodies/{int(identifier) % 256:02x}/{identifier}-{token}-a{attribute_number}.bin"
                    data = values.tobytes()
                    pending_files.append((relative, data))
                    cache_bytes += len(data)
                    stored_attributes.append(dict(id=name, data_type=values.dtype.str,
                                                  shape=list(values.shape), bytes=len(data), path=relative))
                old_bytes = json.loads(old["data"]).get("cache_bytes", 0) if old else 0
                if cache_used - old_bytes + cache_bytes > max_cache_bytes:
                    status = "cache_budget_exhausted"
                    break
                if shutil.disk_usage(self.cache_root).free < cache_bytes + 256 * 1024**2:
                    raise OSError("Geometry cache free space is below the next-body write plus 256 MiB reserve")
                for relative, data in pending_files:
                    _atomic(self.cache_root / relative, data)
                bounds = skeleton.bounds
                center = (np.asarray(bounds[0]) + bounds[1]) / 2
                tile = ":".join(str(math.floor(x / TILE_UM)) for x in center)
                value = dict(bounds=bounds, center=center.tolist(), tile=tile,
                             tile_bounds=[[math.floor(x / TILE_UM) for x in end] for end in bounds],
                             vertices=len(skeleton.positions), edges=len(skeleton.edges),
                             radius=skeleton.has_radius, attributes=list(skeleton.attributes),
                             stored_attributes=stored_attributes,
                             annotated=None if self.annotation_ids is None else identifier in self.annotation_ids,
                             lods=lods, cache_bytes=cache_bytes)
                connection.execute("INSERT OR REPLACE INTO bodies VALUES (?,?,?,?,?,?,?)", (
                    identifier, item["bytes"], item["mtime_ns"], item["generation"], "available",
                    json.dumps(value, separators=(",", ":")), self._representatives(skeleton)))
                connection.commit()  # Publish only after all LOD files succeeded.
                cache_used += cache_bytes - old_bytes
                processed += 1
                if progress:
                    progress(dict(stage="skeleton-cache", completed=position + 1,
                                  total=len(snapshot["files"]), body_id=identifier,
                                  processed=processed, reused=reused, invalid=invalid,
                                  input_bytes=consumed, snapshot_id=snapshot["snapshot_id"]))
            remaining = connection.execute("SELECT count(*) FROM expected WHERE body_id NOT IN (SELECT body_id FROM bodies WHERE status='available')").fetchone()[0]
            report = dict(status=status, snapshot_id=snapshot["snapshot_id"],
                          processed=processed, reused=reused, invalid=invalid,
                          input_bytes=consumed, remaining=remaining,
                          elapsed_seconds=time.perf_counter() - started,
                          budget=dict(max_files=max_files, max_bytes=max_bytes, max_cache_bytes=max_cache_bytes),
                          attempted=attempted, cache_bytes=cache_used)
            report["downloaded_unprocessed"] = connection.execute("SELECT count(*) FROM expected WHERE downloaded=1 AND body_id NOT IN (SELECT body_id FROM bodies)").fetchone()[0]
            self._set_meta(connection, dict(status="ready", processing=report))
            connection.commit()
            report["overview"] = self.overview(limit=20)
            return report
        except Exception as exception:
            self._set_meta(connection, dict(status="ready", processing=dict(status="failed", error=str(exception),
                                                                           processed=processed, reused=reused,
                                                                           input_bytes=consumed)))
            connection.commit()
            raise
        finally:
            connection.close()
