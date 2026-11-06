"""Full morphology index with spatial queries and compact principal paths.

SQLite transactions publish a whole bounded batch, including its overview and
RTree. Source files and the previous four-level cache remain read only.
"""
import hashlib
import json
import math
import shutil
import sqlite3
import struct
import threading
import time
from pathlib import Path

import numpy as np

from .precomputed import body_id, metadata, pack, parse, rules_id, simplify
from .skeleton_cache import SkeletonCache, _atomic, _cancelled, _positive, MAX_FILE_BYTES
from .skeleton_overview import principal_paths, encode_paths, decode_paths, path_segments

VERSION = 'skeleton-spatial-v2'
DETAIL_BUDGET = 256 * 1024**2
OVERVIEW_TOLERANCE = 16.
OVERVIEW_SEGMENTS = 48


class SpatialSkeletonCache(SkeletonCache):
    def __init__(self, source_root, cache_root=None, index_id=None, annotation_ids=None):
        super().__init__(source_root, cache_root, index_id, annotation_ids)
        self.legacy = SkeletonCache(source_root, self.cache_root, index_id, annotation_ids)
        self.cache_root = self.cache_root / 'spatial-v2'
        self.database = self.cache_root / 'spatial.sqlite3'
        self.detail_mutex = threading.Lock()

    def _connect(self, write=False):
        if not write and not self.database.exists():
            return None
        if write:
            self.cache_root.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.database if write else self.database.as_uri() + '?mode=ro',
                              uri=not write, timeout=30)
        con.row_factory = sqlite3.Row
        if write:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('PRAGMA synchronous=FULL')
            con.executescript('''
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS objects(
                    ordinal INTEGER PRIMARY KEY, body_id TEXT UNIQUE NOT NULL,
                    source_size INTEGER NOT NULL, generation TEXT, status TEXT NOT NULL,
                    data TEXT, paths BLOB, cell TEXT, rank TEXT);
                CREATE INDEX IF NOT EXISTS pending ON objects(status,ordinal);
                CREATE INDEX IF NOT EXISTS cells ON objects(status,cell,rank);
                CREATE VIRTUAL TABLE IF NOT EXISTS boxes USING rtree(
                    ordinal,minx,maxx,miny,maxy,minz,maxz);
            ''')
        return con

    def _identity(self, con, cache_id=None):
        meta = self._meta(con)
        if meta.get('index_id') != self.index_id:
            raise ValueError('Geometry index identity differs from this workspace')
        if meta.get('source_root') != str(self.source_root):
            raise ValueError('Geometry source directory does not match the prepared cache')
        if cache_id and cache_id != meta.get('cache_id'):
            raise ValueError('Geometry cache identity does not match this scene')
        return meta

    def _initialize(self, con):
        prior = self._meta(con)
        rules = metadata(self.source_root / 'info')
        identity = 'skeleton-' + rules_id(dict(version=VERSION, rules=rules,
            source=str(self.source_root), index_id=self.index_id,
            tolerance=OVERVIEW_TOLERANCE, max_segments=OVERVIEW_SEGMENTS))[:24]
        if prior:
            self._identity(con)
            if prior['cache_id'] != identity:
                raise ValueError('Geometry processing definition changed; use a separate cache')
            return prior
        # Cached official listing is already locally verified by the user. Freeze
        # it once, without enumerating the directory again or hashing payloads.
        pages = sorted(self.control_root.glob('listing-*.json'))
        if not pages:
            raise ValueError('Completed local download manifest is missing')
        ordinal = 0
        complete = False
        for number, path in enumerate(pages):
            if path.name != f'listing-{number:04d}.json':
                raise ValueError('Local manifest has a missing page')
            page = json.loads(path.read_text(encoding='utf-8'))
            rows = []
            for item in page.get('items', []):
                identifier = item['name'].rsplit('/', 1)[-1]
                if identifier == 'info':
                    continue
                identifier = body_id(identifier)
                ordinal += 1
                rows.append((ordinal, identifier, int(item['size']),
                             str(item.get('generation', '')), 'pending'))
            con.executemany('INSERT INTO objects(ordinal,body_id,source_size,generation,status) VALUES (?,?,?,?,?)', rows)
            complete = not bool(page.get('nextPageToken'))
        if not complete:
            raise ValueError('Local listing is incomplete; no input snapshot published')
        meta = dict(cache_id=identity, cache_version=VERSION, index_id=self.index_id,
                    source_root=str(self.source_root), coordinate_rule=rules,
                    snapshot_id=rules_id(dict(identity=identity, count=ordinal)),
                    expected=ordinal, created=time.time(), status='ready',
                    coverage=dict(processed=0, valid=0, invalid=0, over_limit=0,
                        annotated=0, unannotated=0, vertices=0, edges=0,
                        overview_bytes=0, source_bytes=0), bounds=None,
                    processing=dict(seconds=0, attempted=0))
        self._set_meta(con, meta)
        con.commit()
        return meta

    def _entry(self, row):
        data = json.loads(row['data'] or '{}')
        data.update(body_id=row['body_id'], status=row['status'], source_size=row['source_size'])
        if row['status'] == 'available':
            # Upper bounds before a lazy level has been generated. No imaginary
            # simplification ratio is used for memory admission.
            data['lods'] = [dict(level=level, vertices=data['vertices'],
                edges=data['edges'], bytes=8+16*data['vertices']+8*data['edges'],
                estimated=True, tolerance_um=(0.,1.,4.,16.)[level]) for level in range(4)]
        return data

    def overview(self, limit=0, offset=0):
        if not isinstance(limit, int) or not 0 <= limit <= 5000 or not isinstance(offset, int) or offset < 0:
            raise ValueError('Invalid catalog limit or offset')
        con = self._connect()
        if con is None:
            return dict(status='unprepared', cache_id=None, index_id=self.index_id,
                        entries=[], entry_count=0, coverage=dict(valid=0, processed=0))
        try:
            meta = self._identity(con)
            coverage = dict(meta['coverage'])
            coverage.update(expected=meta['expected'], downloaded=meta['expected'],
                pending_download=0, downloaded_unprocessed=meta['expected']-coverage['processed'],
                cache_bytes=self._disk_bytes())
            entries = [self._entry(r) for r in con.execute(
                "SELECT * FROM objects WHERE status='available' ORDER BY ordinal LIMIT ? OFFSET ?", (limit,offset))]
            status = meta['status']
            if status == 'preparing' and not self._processor_busy():
                status = 'interrupted'
            return dict(status=status, cache_id=meta['cache_id'], cache_version=VERSION,
                index_id=self.index_id, coordinate_rule=meta['coordinate_rule'], bounds=meta['bounds'],
                coverage=coverage, entries=entries, entry_count=coverage['valid'],
                limit=limit, offset=offset, has_more=offset+len(entries)<coverage['valid'],
                processing=meta['processing'], background=meta.get('background', {}),
                snapshot_id=meta['snapshot_id'])
        finally:
            con.close()

    def _disk_bytes(self):
        # Only bounded derived files (not the raw directory).
        total = sum(p.stat().st_size for p in self.cache_root.glob('*.sqlite3*'))
        total += sum(p.stat().st_size for p in self.cache_root.glob('background-*.bin'))
        total += sum(p.stat().st_size for p in (self.cache_root/'details').glob('*.bin'))
        return total

    def locate(self, identifiers):
        if not isinstance(identifiers, (list,tuple)) or len(identifiers)>20000:
            raise ValueError('locate accepts at most 20000 exact IDs')
        identifiers = list(dict.fromkeys(body_id(i) for i in identifiers))
        con = self._connect()
        if con is None:
            return dict(cache_id=None,nodes=[dict(body_id=i,status='unprepared') for i in identifiers])
        try:
            meta = self._identity(con)
            nodes = []
            for identifier in identifiers:
                row = con.execute('SELECT * FROM objects WHERE body_id=?',(identifier,)).fetchone()
                nodes.append(self._entry(row) if row else dict(body_id=identifier,status='missing'))
            return dict(cache_id=meta['cache_id'],coordinate_rule=meta['coordinate_rule'],nodes=nodes)
        finally:
            con.close()

    def query_view(self, bounds, limit=512, cache_id=None, planes=None):
        b = np.asarray(bounds, float)
        if b.shape != (2,3) or not np.isfinite(b).all() or np.any(b[1]<b[0]):
            raise ValueError('bounds must be finite [minimum xyz,maximum xyz]')
        _positive(limit,'limit',2048)
        con = self._connect()
        if con is None:
            raise ValueError('Geometry is not prepared')
        try:
            meta = self._identity(con,cache_id)
            where = 'b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=? AND b.minz<=? AND b.maxz>=?'
            args = [b[1,0],b[0,0],b[1,1],b[0,1],b[1,2],b[0,2]]
            if planes is not None:
                clip=np.asarray(planes,float)
                if clip.ndim!=2 or clip.shape[1]!=4 or not 1<=len(clip)<=6 or not np.isfinite(clip).all() or np.any(np.linalg.norm(clip[:,:3],axis=1)<1e-12):
                    raise ValueError('planes must contain 1..6 finite nonzero [nx,ny,nz,d] halfspaces')
                # RTree broad phase, followed by conservative halfspace tests on
                # its numeric bounds. No object JSON is fetched for false hits.
                for nx,ny,nz,d in clip:
                    where+=' AND (?*(CASE WHEN ?>=0 THEN b.maxx ELSE b.minx END)+?*(CASE WHEN ?>=0 THEN b.maxy ELSE b.miny END)+?*(CASE WHEN ?>=0 THEN b.maxz ELSE b.minz END)+?)>=0'
                    args.extend((nx,nx,ny,ny,nz,nz,d))
            count = con.execute('SELECT count(*) FROM boxes b WHERE '+where,args).fetchone()[0]
            # RTree intersection, not centroid/tile containment. Long objects
            # crossing any queried region are eligible, once per body.
            rows = con.execute('SELECT o.body_id,o.status,o.source_size,o.data FROM boxes b JOIN objects o USING(ordinal) WHERE '+where+
                ' ORDER BY o.rank LIMIT ?',(*args,limit))
            return dict(cache_id=meta['cache_id'],bounds=b.tolist(),matched_count=count,
                        entries=[self._entry(row) for row in rows],limit=limit,truncated=count>limit)
        finally:
            con.close()

    def _background_rows(self, rows, max_edges, tolerance=32.):
        points, identifiers = [], []
        used, bodies = 0, 0
        for row in rows:
            segments = path_segments(decode_paths(row['paths']),tolerance)
            if not len(segments) or used+len(segments)>max_edges:
                continue
            # Whole simplified paths, never isolated prefix segments.
            points.append(segments)
            identifiers.append(np.full(len(segments),int(row['body_id']),dtype='<u8'))
            used += len(segments)
            bodies += 1
        xyz = np.concatenate(points) if points else np.empty((0,6),'<f4')
        ids = np.concatenate(identifiers) if identifiers else np.empty(0,'<u8')
        return struct.pack('<II',len(ids),0)+xyz.tobytes()+ids.tobytes(), bodies, len(ids)

    def _publish_background(self, con, meta):
        # Spatially stratified order: first object of every occupied cell, then
        # second of every cell. Hash tie breaks are stable, not file-list prefixes.
        result = {}
        for budget in (64000,300000):
            rows = con.execute("SELECT body_id,paths FROM (SELECT body_id,paths,cell,rank,ROW_NUMBER() OVER(PARTITION BY cell ORDER BY rank) tier FROM objects WHERE status='available') ORDER BY tier,cell,rank")
            data,bodies,segments = self._background_rows(rows,budget)
            _atomic(self.cache_root/f'background-{budget}.bin',data)
            result[str(budget)] = dict(drawn_bodies=bodies,segment_count=segments,bytes=len(data),
                path_tolerance_um=32.,available_bodies=meta['coverage']['valid'])
        meta['background'] = result
        self._set_meta(con,dict(background=result))
        con.commit()

    def background_bytes(self, max_edges=64000, bounds=None, planes=None):
        _positive(max_edges,'max_edges',350000)
        con = self._connect()
        if con is None:
            return struct.pack('<II',0,0), dict(segment_count=0,drawn_bodies=0)
        try:
            meta = self._identity(con)
            if bounds is None:
                key = '64000' if max_edges<300000 else '300000'
                path = self.cache_root/f'background-{key}.bin'
                info = meta.get('background',{}).get(key)
                if not info or not path.exists():
                    return struct.pack('<II',0,0),dict(cache_id=meta['cache_id'],status='not_published',segment_count=0,drawn_bodies=0)
                if info['segment_count']>max_edges:
                    raise ValueError('Requested background budget is below the published level; use at least 64000 segments')
                return path.read_bytes(),dict(info,cache_id=meta['cache_id'])
            view = self.query_view(bounds,2048,meta['cache_id'],planes=planes)
            rows = (con.execute('SELECT body_id,paths FROM objects WHERE body_id=?',(entry['body_id'],)).fetchone() for entry in view['entries'])
            data,bodies,segments = self._background_rows(rows,max_edges,16.)
            return data,dict(cache_id=meta['cache_id'],drawn_bodies=bodies,segment_count=segments,
                matched_count=view['matched_count'],truncated=view['truncated'],bytes=len(data))
        finally:
            con.close()

    def detail(self, identifier, level=0, cache_id=None):
        identifier = body_id(identifier)
        if isinstance(level,bool) or not isinstance(level,int) or not 0<=level<=3:
            raise ValueError('level must be 0..3')
        con = self._connect()
        if con is None:
            raise ValueError('Geometry is not prepared')
        try:
            meta = self._identity(con,cache_id)
            row = con.execute('SELECT * FROM objects WHERE body_id=?',(identifier,)).fetchone()
            if row is None or row['status']!='available':
                raise ValueError(f'{identifier}: no valid processed skeleton')
            expected = row['source_size']
            prepared_mtime = json.loads(row['data'])['source_mtime_ns']
        finally:
            con.close()
        # Reuse compatible already-published v1 details without rewriting them.
        if self.legacy.database.exists():
            old = self.legacy.locate([identifier])['nodes'][0]
            if old.get('status')=='available' and old.get('source_size')==expected and old.get('source_mtime_ns')==prepared_mtime:
                return self.legacy.detail(identifier,level)
        from .local_tasks import LocalSlot
        with self.detail_mutex, LocalSlot(self.cache_root,name='detail.lock'):
            path = self.cache_root/'details'/f'{identifier}-{level}.bin'
            if path.exists():
                path.touch()
                return path.read_bytes()
            data = (self.source_root/identifier).read_bytes()
            if len(data)!=expected:
                raise ValueError(f'{identifier}: source length changed after processing')
            skeleton = parse(data,identifier,meta['coordinate_rule'])
            if level:
                skeleton = simplify(skeleton,(0.,1.,4.,16.)[level])
            result = pack(skeleton)
            if len(result)>16*1024**2:
                raise ValueError('Detail exceeds 16 MiB response budget; request a coarser level')
            files = sorted((self.cache_root/'details').glob('*.bin'),key=lambda p:p.stat().st_mtime)
            used = sum(p.stat().st_size for p in files)
            for old in files:
                if used+len(result)<=DETAIL_BUDGET:
                    break
                size=old.stat().st_size
                old.unlink()
                used-=size
            _atomic(path,result)
            return result

    def prepare(self,max_files=None,max_bytes=512*1024**2,cancel=None,progress=None,
                max_cache_bytes=2048*1024**2):
        return super().prepare(max_files,max_bytes,cancel,progress,max_cache_bytes)

    def _prepare(self,max_files,max_bytes,cancel,progress,max_cache_bytes):
        _positive(max_files,'max_files',1000000,optional=True)
        _positive(max_bytes,'max_bytes',16*1024**3)
        _positive(max_cache_bytes,'max_cache_bytes',16*1024**3)
        con = self._connect(write=True)
        started = time.perf_counter()
        attempted=consumed=0
        status='completed'
        try:
            meta = self._initialize(con)
            coverage=dict(meta['coverage'])
            bounds=meta['bounds']
            pending = con.execute("SELECT count(*) FROM objects WHERE status='pending'").fetchone()[0]
            self._set_meta(con,dict(status='preparing'))
            con.commit()
            while pending:
                if _cancelled(cancel):
                    status='cancelled';break
                if max_files is not None and attempted>=max_files:
                    status='budget_exhausted';break
                # Re-query only pending index rows, not a changing raw directory.
                # Only compact paths/metadata remain resident; larger commits
                # amortize durable SQLite publication without retaining raw files.
                count=min(1024,pending,(max_files-attempted) if max_files else 1024)
                rows=con.execute("SELECT * FROM objects WHERE status='pending' ORDER BY ordinal LIMIT ?",(count,)).fetchall()
                chunk=[]
                for row in rows:
                    if _cancelled(cancel):
                        status='cancelled';break
                    if consumed+row['source_size']>max_bytes:
                        status='budget_exhausted';break
                    identifier=row['body_id']
                    entry=dict(annotated=self.annotation_ids is not None and identifier in self.annotation_ids)
                    state='available';blob=None;box=None
                    try:
                        if row['source_size']>MAX_FILE_BYTES:
                            state='over_limit';raise ValueError('Skeleton source exceeds 128 MiB limit')
                        raw=(self.source_root/identifier).read_bytes()
                        if len(raw)!=row['source_size']:
                            raise ValueError('Final file length does not match frozen local manifest')
                        skeleton=parse(raw,identifier,meta['coordinate_rule'])
                        paths,tolerance=principal_paths(skeleton,OVERVIEW_TOLERANCE,OVERVIEW_SEGMENTS)
                        blob=encode_paths(paths);box=skeleton.bounds
                        entry.update(vertices=len(skeleton.positions),edges=len(skeleton.edges),bounds=box,
                            has_radius=skeleton.has_radius,overview_bytes=len(blob),overview_segments=sum(len(p)-1 for p in paths),
                            tolerance_um=tolerance,source_mtime_ns=(self.source_root/identifier).stat().st_mtime_ns)
                    except (ValueError,OSError) as error:
                        state='over_limit' if state=='over_limit' or 'exceeds limits' in str(error) else 'invalid'
                        entry['error']=str(error)
                    chunk.append((row,state,entry,blob,box))
                    attempted+=1;consumed+=row['source_size']
                if not chunk:
                    break
                new_bytes=sum(len(c[3] or b'')+2048 for c in chunk)
                if self._disk_bytes()+new_bytes>max_cache_bytes or shutil.disk_usage(self.cache_root).free<new_bytes+256*1024**2:
                    raise ValueError('Geometry cache or free-disk budget insufficient; committed batches retained')
                # Paths + index membership publish together; no available row can
                # refer to a partially written geometry overview.
                for row,state,entry,blob,box in chunk:
                    cell=''
                    if box:
                        center=(np.asarray(box[0])+box[1])/2
                        cell=','.join(str(math.floor(float(x)/100.)) for x in center)
                        if bounds is None:bounds=box
                        else:bounds=[np.minimum(bounds[0],box[0]).tolist(),np.maximum(bounds[1],box[1]).tolist()]
                        con.execute('INSERT INTO boxes VALUES (?,?,?,?,?,?,?)',(row['ordinal'],box[0][0],box[1][0],box[0][1],box[1][1],box[0][2],box[1][2]))
                    rank=hashlib.blake2b(row['body_id'].encode(),digest_size=8).hexdigest()
                    con.execute('UPDATE objects SET status=?,data=?,paths=?,cell=?,rank=? WHERE ordinal=?',
                        (state,json.dumps(entry,separators=(',',':')),blob,cell,rank,row['ordinal']))
                    coverage['processed']+=1
                    coverage['source_bytes']+=row['source_size']
                    if state=='available':
                        coverage['valid']+=1
                        coverage['annotated' if entry['annotated'] else 'unannotated']+=1
                        for key in ('vertices','edges','overview_bytes'):coverage[key]+=entry[key]
                    else:coverage[state if state=='over_limit' else 'invalid']+=1
                processing=dict(seconds=meta['processing']['seconds']+time.perf_counter()-started,
                                attempted=coverage['processed'],last_run_attempted=attempted,input_bytes=consumed)
                self._set_meta(con,dict(coverage=coverage,bounds=bounds,processing=processing))
                con.commit()
                pending-=len(chunk)
                if progress:progress(dict(phase='morphology',processed=coverage['processed'],completed=coverage['processed'],
                    total=meta['expected'],remaining=pending,seconds=processing['seconds'],overview_bytes=coverage['overview_bytes']))
                if status!='completed':break
            meta.update(coverage=coverage,bounds=bounds)
            if attempted or not meta.get('background') or any(not (self.cache_root/f'background-{budget}.bin').exists() for budget in (64000,300000)):
                if progress:progress(dict(phase='background',processed=coverage['processed'],
                    completed=coverage['processed'],total=meta['expected'],remaining=pending,
                    overview_bytes=coverage['overview_bytes']))
                self._publish_background(con,meta)
            self._set_meta(con,dict(status=status))
            con.commit()
            con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            return dict(status=status,attempted=attempted,input_bytes=consumed,reused=meta['expected']-pending-attempted,
                remaining=pending,seconds=time.perf_counter()-started,coverage=coverage,cache_id=meta['cache_id'])
        except Exception:
            con.rollback()
            if self._meta(con):
                self._set_meta(con,dict(status='failed'));con.commit()
            raise
        finally:
            con.close()
