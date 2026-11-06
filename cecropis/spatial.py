"""Traced annotation positions in unmirrored MaleCNS EM space; no network.

Annotations are DVID xyz voxel locations, at 8 nm resolution for this source.
Only known source provenance enables that conversion; never infer from ranges.
GPU transport rounds display coordinates to float32; identity remains uint64.
"""
import hashlib
import json
import math
import os
from pathlib import Path
from uuid import uuid4
import numpy as np
from .global_index import _body_id
from .geometry import GeometryStore

RULE = dict(version=1,coordinate_space='male-cns-em',units='um',source_units_nm=8,
    fields=['somaLocation','tosomaLocation'],axis_order='xyz',scale_to_um=.008,
    transform='none',selection='valid soma first; otherwise valid tosoma endpoint',category='status=Traced')
FIELDS=('superclass','class','type','somaSide')
KINDS=('missing','soma','tosoma-endpoint','invalid')
RECORD=np.dtype([('id','<u8'),('xyz','<f4',(3,)),('kind','u1'),('padding','u1',(3,))])
MAX_IDS=200000

def exact_ids(values):
    if not isinstance(values,list) or len(values)>MAX_IDS:raise ValueError('Spatial selection requires at most 200000 exact IDs')
    ids=[str(_body_id(v)) for v in values]
    if len(set(ids))!=len(ids):raise ValueError('Spatial selection contains duplicate IDs')
    return ids

def _point(text):
    if text is None or text=='':return None,False
    try:
        value=json.loads(text) if isinstance(text,str) else text
        if value is None:return None,False
        if not isinstance(value,list) or len(value)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in value):return None,True
        return [v*.008 for v in value],False
    except (ValueError,TypeError):return None,True

class SpatialStore:
    def __init__(self,index,cache_root=None,geometry_root=None):
        self.index=index
        if index.manifest.get('source_version')!='MaleCNS v1.0 minconf=0.5':
            raise ValueError('Spatial coordinate rule is only confirmed for MaleCNS v1.0 minconf=0.5; source units/space must be confirmed')
        stat=(index.path/'annotations.sqlite').stat()
        identity=dict(source_index_id=index.manifest['index_id'],rule=RULE,annotation_bytes=stat.st_size,annotation_mtime_ns=stat.st_mtime_ns)
        self.identity=identity;self.key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        self.cache_root=Path(cache_root or index.path.parent/'spatial-cache')
        self.geometry_root=Path(geometry_root or index.path.parent.parent/'geometry'/'male-cns-em')
        self.data=None;self.header=None

    def prepare(self,cancel=lambda:False,progress=lambda p:None):
        if self.data is not None:return self.overview()
        path=self.cache_root/self.key
        if (path/'spatial.json').is_file() and (path/'positions.npz').is_file():
            header=json.loads((path/'spatial.json').read_text(encoding='utf-8'))
            if header['identity']!=self.identity:raise ValueError('Spatial cache identity mismatch')
            with np.load(path/'positions.npz',allow_pickle=False) as a:self.data={k:a[k] for k in a.files}
            self.header=header;return self.overview()
        ids=[];positions=[];kinds=[];groups={field:[] for field in FIELDS}
        invalid_soma=invalid_tosoma=valid_tosoma=0
        connection=self.index._connect()
        try:
            columns={r[1] for r in connection.execute('PRAGMA table_info(nodes)')}
            required={'somaLocation','tosomaLocation','status',*FIELDS}
            if not required<=columns:raise ValueError('Spatial annotation fields missing: '+', '.join(sorted(required-columns)))
            cursor=connection.execute('SELECT bodyId,somaLocation,tosomaLocation,'+','.join('"'+f+'"' for f in FIELDS)+' FROM nodes WHERE status=? ORDER BY bodyId',('Traced',))
            while True:
                if cancel():raise ValueError('Spatial preparation cancelled; no complete cache published')
                block=cursor.fetchmany(2048)
                if not block:break
                if len(ids)+len(block)>MAX_IDS:raise ValueError('Traced annotation count exceeds the 200000-position budget')
                for body,soma,tosoma,*labels in block:
                    s,si=_point(soma);t,ti=_point(tosoma)
                    invalid_soma+=si;invalid_tosoma+=ti;valid_tosoma+=t is not None
                    ids.append(body);positions.append(s if s is not None else t if t is not None else [np.nan]*3)
                    kinds.append(1 if s is not None else 2 if t is not None else 3 if si or ti else 0)
                    for field,label in zip(FIELDS,labels):groups[field].append(label or '')
                progress(dict(phase='spatial_annotations',completed=len(ids)))
        finally:connection.close()
        data=dict(ids=np.asarray(ids,dtype=np.int64),positions=np.asarray(positions,dtype=np.float64).reshape(-1,3),kinds=np.asarray(kinds,dtype=np.uint8))
        dictionaries={}
        for field,labels in groups.items():
            names,codes=np.unique(np.asarray(labels,dtype=str),return_inverse=True)
            dictionaries[field]=names.tolist();data[field]=codes.astype(np.uint32)
        valid=data['kinds']>0;valid &= data['kinds']<3
        points=data['positions'][valid]
        header=dict(kind='spatial_positions',identity=self.identity,coordinate_rule=RULE,cache_id=self.key,
            traced_count=len(ids),soma_count=kinds.count(1),other_position_count=kinds.count(2),missing_count=kinds.count(0),invalid_count=kinds.count(3),
            invalid_soma_fields=int(invalid_soma),invalid_tosoma_fields=int(invalid_tosoma),valid_tosoma_fields=int(valid_tosoma),
            position_count=int(valid.sum()),bounds=[points.min(axis=0).tolist(),points.max(axis=0).tolist()] if len(points) else None,
            groups=dictionaries,record_bytes=RECORD.itemsize,transport_bytes=len(ids)*RECORD.itemsize,chunk_size=20000,
            coordinate_kinds=list(KINDS),display_dtype='float32',identity_dtype='uint64 little-endian')
        if cancel():raise ValueError('Spatial preparation cancelled; no complete cache published')
        self.cache_root.mkdir(parents=True,exist_ok=True)
        stage=self.cache_root/('.partial-'+uuid4().hex);stage.mkdir()
        try:
            np.savez_compressed(stage/'positions.npz',**data)
            (stage/'spatial.json').write_text(json.dumps(header,ensure_ascii=False,indent=2),encoding='utf-8')
            if cancel():raise ValueError('Spatial preparation cancelled; partial cache is not usable')
            if not path.exists():os.replace(stage,path)
            else:
                for f in stage.iterdir():f.unlink()
                stage.rmdir()
        except Exception:
            # Only this freshly created staging folder is removed, not an index.
            for f in stage.iterdir():f.unlink()
            stage.rmdir();raise
        self.data=data;self.header=header
        return self.overview()

    def overview(self):
        if self.data is None:return self.prepare()
        return self.header

    def chunk(self,offset=0,limit=20000):
        self.prepare()
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=20000:raise ValueError('Spatial chunk: offset>=0, 1<=limit<=20000')
        out=np.zeros(min(limit,max(0,len(self.data['ids'])-offset)),dtype=RECORD)
        stop=offset+len(out);out['id']=self.data['ids'][offset:stop];out['xyz']=self.data['positions'][offset:stop];out['kind']=self.data['kinds'][offset:stop]
        return out.tobytes()

    def locate(self,body_ids):
        self.prepare();ids=exact_ids(body_ids)
        values=np.asarray([int(b) for b in ids],dtype=np.int64);p=np.searchsorted(self.data['ids'],values)
        nodes=[]
        for body,i in zip(ids,p):
            if i<len(self.data['ids']) and int(self.data['ids'][i])==int(body):
                kind=int(self.data['kinds'][i]);nodes.append(dict(bodyId=body,position=self.data['positions'][i].tolist() if kind in (1,2) else None,position_kind=KINDS[kind],browse_member=True))
            else:
                self.index.position(body) # reject absent graph IDs; do not invent a point
                nodes.append(dict(bodyId=body,position=None,position_kind='outside-traced-browse',browse_member=False))
        return dict(source_index_id=self.identity['source_index_id'],coordinate_rule=RULE,nodes=nodes,
            selection_count=len(ids),located_count=sum(n['position'] is not None for n in nodes))

    def filter(self,field,value):
        self.prepare()
        if field not in FIELDS or not isinstance(value,str):raise ValueError('Use an available exact spatial annotation filter')
        names=self.header['groups'][field]
        indices=np.flatnonzero(self.data[field]==names.index(value)) if value in names else np.empty(0,dtype=int)
        kinds=self.data['kinds'][indices]
        return dict(source_index_id=self.identity['source_index_id'],field=field,value=value,body_ids=[str(i) for i in self.data['ids'][indices]],
            member_count=len(indices),position_count=int(np.isin(kinds,[1,2]).sum()),missing_position_count=int((~np.isin(kinds,[1,2])).sum()))

    def edges(self,pairs,max_edges=2000):
        if type(max_edges) is not int or not 1<=max_edges<=2000 or not isinstance(pairs,list) or len(pairs)>max_edges:raise ValueError('Spatial edge display budget is 1..2000 exact edges')
        rows=[];seen=set()
        for pair in pairs:
            if not isinstance(pair,list) or len(pair)!=2:raise ValueError('Expected exact pre/post pair')
            pre,post=map(lambda v:str(_body_id(v)),pair)
            if (pre,post) in seen:continue
            seen.add((pre,post));a=self.index.position(pre);b=self.index.position(post);count=int(self.index.outgoing[a,b])
            if count<=0:raise ValueError(f'{pre}->{post} is not a real directed edge')
            rows.append(dict(pre_id=pre,post_id=post,edge_id=pre+'->'+post,count=count,weight=count/int(self.index.total_input[b]) if self.index.total_input[b]>0 else None))
        locations=self.locate(list(dict.fromkeys(b for row in rows for b in (row['pre_id'],row['post_id']))))
        positions={r['bodyId']:r['position'] for r in locations['nodes']}
        for row in rows:row.update(pre_position=positions[row['pre_id']],post_position=positions[row['post_id']])
        return dict(edges=rows,edge_count=len(rows),drawable_count=sum(r['pre_position'] is not None and r['post_position'] is not None for r in rows),position_kind='abstract directed connection between annotation positions')

    def geometry(self,ids,load=False):
        ids=exact_ids(ids)
        if len(ids)>8:raise ValueError('At most 8 local skeleton objects may be loaded')
        nodes=self.index.nodes(ids);store=GeometryStore(dict(nodes=nodes),self.geometry_root,max_points=100000,max_bytes=16*1024*1024)
        rows=[];budget=0;point_budget=0
        for body in ids:
            path=store._path(body)
            if not path.is_file():rows.append(dict(bodyId=body,status='missing'));continue
            budget+=path.stat().st_size
            if budget>32*1024*1024:raise ValueError('Selected SWC files exceed 32 MiB aggregate budget')
            if not load:rows.append(dict(bodyId=body,status='local',bytes=path.stat().st_size));continue
            try:
                skeleton=store.skeleton(body)
                point_budget+=skeleton['point_count']
                if point_budget>200000:raise MemoryError('Selected skeletons exceed the 200000 total-point budget')
                rows.append(dict(bodyId=body,status='loaded',skeleton=skeleton))
            except ValueError as e:rows.append(dict(bodyId=body,status='invalid',error=str(e)))
        return dict(coordinate_rule=RULE,objects=rows,max_objects=8,max_points_per_object=100000,max_total_points=200000,max_total_bytes=32*1024*1024)

def validate_spatial_state(value,source_index_id):
    if not isinstance(value,dict) or set(value)-{'source_index_id','coordinate_rule','camera','filter','highlight_ids','selected_nodes','focus_node','isolate','mode','replay_id','state_step','show_edges','skeleton_ids','edge_pairs','selected_edge','geometry','display_layers'}:raise ValueError('Unsupported spatial display state')
    value=json.loads(json.dumps(value,allow_nan=False))
    layers=value.get('display_layers')
    if layers is not None:
        if not isinstance(layers,dict) or set(layers)-{'points','connections','sidebar'} or any(type(v) is not bool for v in layers.values()):
            raise ValueError('Spatial display layers must be named booleans')
    if value.get('source_index_id')!=source_index_id or value.get('coordinate_rule')!=RULE:raise ValueError('Spatial display index or coordinate-space rule mismatch')
    camera=value.get('camera',{})
    if set(camera)!={'center','span','yaw','pitch','zoom','pan'}:raise ValueError('Spatial camera needs center/span/yaw/pitch/zoom/pan')
    for field,n in [('center',3),('pan',2)]:
        if not isinstance(camera[field],list) or len(camera[field])!=n:raise ValueError('Invalid spatial camera '+field)
    vals=camera['center']+camera['pan']+[camera[k] for k in ('span','yaw','pitch','zoom')]
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in vals) or camera['span']<=0 or not .05<=camera['zoom']<=200:raise ValueError('Invalid finite spatial camera values')
    for field in ('highlight_ids','selected_nodes','skeleton_ids'):value[field]=exact_ids(value.get(field,[]))
    if len(value['skeleton_ids'])>8:raise ValueError('Spatial skeleton object budget exceeded')
    if value.get('focus_node') is not None:exact_ids([value['focus_node']])
    pairs=value.get('edge_pairs',[])
    if not isinstance(pairs,list) or len(pairs)>2000:raise ValueError('Spatial saved edges exceed 2000 pairs')
    value['edge_pairs']=[]
    for pair in pairs:
        if not isinstance(pair,list) or len(pair)!=2:raise ValueError('Spatial saved edges require exact directed pairs')
        value['edge_pairs'].append([str(_body_id(b)) for b in pair])
    selected=value.get('selected_edge')
    if selected is not None and selected not in {a+'->'+b for a,b in value['edge_pairs']}:raise ValueError('Selected spatial edge is not displayed')
    f=value.get('filter')
    if f is not None and (not isinstance(f,dict) or set(f)!={'field','value'} or f['field'] not in FIELDS or not isinstance(f['value'],str)):raise ValueError('Invalid spatial filter')
    if value.get('mode','structure') not in ('structure','baseline','intervention','delta'):raise ValueError('Invalid spatial display mode')
    for field in ('isolate','show_edges'):
        if type(value.get(field,False)) is not bool:raise ValueError('Spatial '+field+' must be boolean')
    if type(value.get('state_step',0)) is not int or value.get('state_step',0)<0:raise ValueError('Spatial state_step must be a nonnegative integer')
    geometry=value.get('geometry')
    if geometry is not None:
        if not isinstance(geometry,dict) or set(geometry)-{'cache_id','coordinate_space','settings','focus_ids'}:
            raise ValueError('Unsupported skeleton display state')
        if geometry.get('coordinate_space')!='male-cns-em':
            raise ValueError('Skeleton display must use unmirrored MaleCNS EM coordinates')
        cache_id=geometry.get('cache_id')
        if cache_id is not None and (not isinstance(cache_id,str) or not 1<=len(cache_id)<=160):
            raise ValueError('Invalid skeleton cache identity')
        settings=geometry.get('settings',{})
        if not isinstance(settings,dict) or set(settings)-{'enabled','diameter','radius_scale','background','quality'}:
            raise ValueError('Unsupported skeleton display settings')
        if type(settings.get('enabled',True)) is not bool:
            raise ValueError('Skeleton enabled must be boolean')
        for field,lower,upper in [('diameter',.001,80),('radius_scale',.01,100),('background',0,1)]:
            if field not in settings:continue
            number=settings[field]
            if type(number) not in (int,float) or not math.isfinite(number) or not lower<=number<=upper:
                raise ValueError('Invalid skeleton display '+field)
        if settings.get('quality','balanced') not in ('low','balanced','high'):
            raise ValueError('Invalid skeleton display quality')
        geometry['focus_ids']=exact_ids(geometry.get('focus_ids',[]))
    return value
