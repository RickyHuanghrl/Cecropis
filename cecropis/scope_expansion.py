"""Budgeted, genuinely nested scope sequences built from the processed index."""
import copy
import hashlib
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import numpy as np
from . import MODEL_VERSION
from .case import load_case, close_case
from .selection import canonical_ids, induced_stats, write_selected_case
from .scope_boundary import _check_index

RULE = 'breadth by adjacent layers; accumulated true connection counts descending; numeric body ID ascending; previous level retained'
_FIELDS = {'budgets', 'added_body_ids', 'hops', 'direction', 'category', 'scan_limit', 'max_internal_edges', 'max_bytes', 'max_disk_bytes'}


def _config(value, core_count):
    if not isinstance(value, dict) or set(value)-_FIELDS:
        raise ValueError('Unknown scope expansion fields')
    cfg = dict(budgets=[], added_body_ids=[], hops=1, direction='incoming', category='neuron',
               scan_limit=5000000, max_internal_edges=5000000, max_bytes=512*1024**2,
               max_disk_bytes=1024**3)
    cfg.update(copy.deepcopy(value))
    budgets = cfg['budgets']
    if not isinstance(budgets, list) or not 1 <= len(budgets) <= 8 or any(type(n) is not int or not core_count <= n <= 200000 for n in budgets):
        raise ValueError('Choose 1..8 node budgets, each core size..200000')
    if any(a >= b for a,b in zip(budgets, budgets[1:])):
        raise ValueError('Expansion node budgets must be strictly increasing')
    if type(cfg['hops']) is not int or not 0 <= cfg['hops'] <= 3:
        raise ValueError('Expansion hops must be 0..3 per level')
    if cfg['direction'] not in ('incoming', 'outgoing', 'both') or cfg['category'] not in ('neuron', 'glia', 'other', 'unannotated', 'all'):
        raise ValueError('Unknown expansion direction or category')
    for key in ('scan_limit','max_internal_edges','max_bytes','max_disk_bytes'):
        if type(cfg[key]) is not int or cfg[key] < 1:
            raise ValueError(key+' must be a positive integer')
    if cfg['scan_limit'] > 10000000:
        raise ValueError('Indexed adjacency scan limit must not exceed 10000000')
    added = cfg['added_body_ids']
    if not isinstance(added, (list,tuple)):
        raise ValueError('Manual expansion seeds require explicit body IDs')
    cfg['added_body_ids'] = canonical_ids(added) if added else []
    return cfg


def _eligible(index, category):
    if category == 'all':return None, None
    if hasattr(index, 'ids_for'):
        if category == 'unannotated':
            return None, set(map(int,index.ids_for({'category':['neuron','glia','other']}, max_count=len(index.ids))))
        return set(map(int,index.ids_for({'category':category}, max_count=len(index.ids)))), None
    eligible = {int(body) for body,node in index.annotations.items() if node.get('category')==category}
    if category=='unannotated':return None, set(map(int,index.annotations))
    return eligible,None


def _allowed(body, eligible, excluded):
    return (eligible is None or body in eligible) and (excluded is None or body not in excluded)


def _members(index, previous_ids, manual, cfg, budget, eligible, excluded, cancel):
    previous = set(map(int,previous_ids)); selected = previous | set(map(int,manual))
    if len(selected)>budget:
        raise ValueError('Node budget cannot retain previous scope and all manual seeds')
    ids = np.array(sorted(selected),dtype=np.int64)
    positions=np.searchsorted(index.ids,ids)
    if np.any(positions>=len(index.ids)) or np.any(index.ids[np.minimum(positions,len(index.ids)-1)]!=ids):
        raise ValueError('Expansion members contain unknown global IDs')
    frontier=sorted(map(int,positions)); selected_positions=set(frontier)
    scanned=0; completed=0; truncated=False; reason=None; observed_candidates=0
    candidate_limit=max(1,(cfg['max_bytes']-budget*8192-4*1024**2)//192)
    directions=('incoming','outgoing') if cfg['direction']=='both' else (cfg['direction'],)
    for layer in range(cfg['hops']):
        candidates={}; scan_incomplete=False; memory_incomplete=False
        for pos in frontier:
            for direction in directions:
                matrix=getattr(index,direction);start,stop=map(int,matrix.indptr[pos:pos+2])
                for first in range(start,stop,65536):
                    if cancel():raise InterruptedError('Scope selection cancelled')
                    last=min(stop,first+65536,first+cfg['scan_limit']-scanned)
                    if last<=first:scan_incomplete=True;break
                    processed=0
                    for neighbor,weight in zip(matrix.indices[first:last],matrix.data[first:last]):
                        processed+=1
                        j=int(neighbor);body=int(index.ids[j])
                        if j not in selected_positions and _allowed(body,eligible,excluded):
                            if j not in candidates and len(candidates)>=candidate_limit:
                                memory_incomplete=True;break
                            candidates[j]=candidates.get(j,0)+int(weight)
                    scanned+=processed
                    if memory_incomplete:scan_incomplete=True;break
                    if last<stop and scanned>=cfg['scan_limit']:scan_incomplete=True;break
                if scan_incomplete:break
            if scan_incomplete:break
        ranked=sorted(candidates,key=lambda pos:(-candidates[pos],int(index.ids[pos])))
        remaining=budget-len(selected_positions)
        frontier=ranked[:remaining];selected_positions.update(frontier)
        completed=layer+1;observed_candidates+=len(ranked)
        if scan_incomplete:
            truncated=True;reason='neighbor_memory_budget' if memory_incomplete else 'neighbor_scan_budget';break
        if len(ranked)>remaining:
            truncated=True;reason='node_budget';break
        if not frontier:break
    result=[str(index.ids[pos]) for pos in sorted(selected_positions)]
    return dict(body_ids=result, seed_ids=[str(body) for body in sorted(previous|set(map(int,manual)))], selected_node_count=len(result),
                retained_node_count=len(previous), added_node_count=len(set(map(int,result))-previous),
                requested_hops=cfg['hops'],hops_completed=completed,max_nodes=budget,direction=cfg['direction'],
                category=cfg['category'],truncated=truncated,truncation_reason=reason,
                neighborhood_scanned_edges=scanned,observed_candidate_count=observed_candidates,
                neighbor_scan_complete=reason not in ('neighbor_scan_budget','neighbor_memory_budget'),selection_rule=RULE,
                ranking_scope='scanned adjacency only' if reason in ('neighbor_scan_budget','neighbor_memory_budget') else 'complete adjacent layer')


def _groups(case):
    saved=case['manifest'].get('groups')
    if saved:return copy.deepcopy(saved)
    result={role:{} for role in ('input','internal','output')}
    for node in case['nodes']:
        for role in result:
            labels=node.get('memberships',{}).get(role,[]) if 'memberships' in node else ([node.get('group_label',node.get('type'))] if node.get('role')==role else [])
            for label in labels:result[role].setdefault(label,[]).append(str(node['bodyId']))
    return result


def _content_key(index_id, bodies, groups):
    data=dict(source_index_id=index_id,body_ids=sorted(bodies,key=int),groups=groups)
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _estimates(node_count, edges, candidate_count):
    # Data/index storage is exact-format arithmetic; JSON and peak work are
    # deliberately estimates, never a promise based on node count alone.
    # <=200000 nodes and <=2^31-1 edges use SciPy int32 structural arrays:
    # two matrices, each int64/float64 values + int32 columns + int32 offsets.
    matrix_bytes=edges*24+(node_count+1)*8
    json_bytes=node_count*4096+1024*1024
    return dict(csr_arrays_bytes_exact=matrix_bytes,
                estimated_disk_bytes=matrix_bytes+json_bytes,
                estimated_peak_memory_bytes=edges*64+node_count*8192+candidate_count*192+4*1024**2,
                estimated_node_metadata_bytes=json_bytes,
                estimate_basis='CSR numeric payload exact (excluding .npy headers); conservative metadata and bounded adjacency work estimates, not a measured peak')


def _preview(index, base, base_path, value, cancel, progress):
    _check_index(index,base)
    core_ids=canonical_ids([str(node['bodyId']) for node in base['nodes']]);cfg=_config(value,len(core_ids))
    eligible,excluded=_eligible(index,cfg['category'])
    rejected=[body for body in cfg['added_body_ids'] if not _allowed(int(body),eligible,excluded)]
    if rejected:raise ValueError('Manual seeds excluded by category rule: '+', '.join(rejected))
    groups=_groups(base);previous=core_ids;levels=[]; cumulative_disk=0
    for level,budget in enumerate(cfg['budgets'],1):
        if cancel():raise InterruptedError('Scope preview cancelled')
        selection=_members(index,previous,cfg['added_body_ids'],cfg,budget,eligible,excluded,cancel)
        bodies=selection['body_ids'];errors=[]
        # Membership is retained even when this level exceeds build resources.
        try:
            stats=induced_stats(index,bodies,scan_limit=cfg['scan_limit'],max_edges=cfg['max_internal_edges'],cancel=cancel)
            if not stats['scan_complete']:
                errors.append(f"Induced-edge scan needs {stats['required_edges']} edges; scan_limit={cfg['scan_limit']}")
        except MemoryError as error:
            stats=dict(scan_complete=False,internal_edges=None,internal_contacts=None,required_edges=None,scanned_edges=0)
            errors.append(str(error))
        estimates=None
        if stats['internal_edges'] is not None:
            estimates=_estimates(len(bodies),stats['internal_edges'],selection['observed_candidate_count'])
            cumulative_disk+=estimates['estimated_disk_bytes']
            if estimates['estimated_peak_memory_bytes']>cfg['max_bytes']:
                errors.append(f"Estimated peak memory {estimates['estimated_peak_memory_bytes']} exceeds max_bytes={cfg['max_bytes']}")
            if cumulative_disk>cfg['max_disk_bytes']:
                errors.append(f"Sequence estimated disk {cumulative_disk} exceeds max_disk_bytes={cfg['max_disk_bytes']}")
        item=dict(level=level,budget=budget,retained_node_count=len(previous),
                  added_node_count=len(set(bodies)-set(previous)),node_count=len(bodies),body_ids=bodies,
                  selection=selection,internal_edges=stats['internal_edges'],internal_contacts=stats['internal_contacts'],
                  internal_edge_count_exact=stats['scan_complete'],induced_scan_required_edges=stats['required_edges'],
                  estimates=estimates,status='preview',build_allowed=not errors,errors=errors,
                  content_key=_content_key(index.manifest['index_id'],bodies,groups))
        levels.append(item);previous=bodies
        progress(dict(phase='preview',level=level,level_count=len(cfg['budgets']),node_count=len(bodies)))
    return dict(kind='scope_expansion',schema_version=1,status='preview',config=cfg,
                identity=dict(base_case_id=base['manifest']['case_id'],source_index_id=index.manifest['index_id'],model_version=MODEL_VERSION),
                base=dict(case_id=base['manifest']['case_id'],case_path=str(Path(base_path).resolve()),node_count=len(core_ids),body_ids=core_ids,
                          selection=copy.deepcopy(base['manifest'].get('selection',{}))),
                groups=groups,default_experiment=copy.deepcopy(base['manifest'].get('default_experiment',{})),
                levels=levels,build_allowed=all(level['build_allowed'] for level in levels),
                estimated_sequence_disk_bytes=cumulative_disk,selection_rule=RULE)


def preview_expansion(index, base_case_path, config):
    base=load_case(base_case_path)
    try:return _preview(index,base,base_case_path,config,lambda:False,lambda value:None)
    finally:close_case(base)


def _reusable(cases_root, key, index_id):
    # Only completed manifest-bearing direct children are runnable scopes.
    for path in sorted(Path(cases_root).iterdir()) if Path(cases_root).exists() else []:
        manifest_path=path/'manifest.json'
        if path.name.startswith('.') or not manifest_path.is_file():continue
        try:
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest.get('source_index_id')!=index_id:continue
            bodies=manifest.get('selection',{}).get('body_ids')
            groups=manifest.get('groups')
            if bodies and groups and _content_key(index_id,bodies,groups)==key:
                needed=['nodes.json']+[f'{name}_{part}.npy' for name in ('counts','propagation') for part in ('data','indices','indptr')]
                if all((path/name).is_file() for name in needed):return path,manifest
        except (ValueError,OSError):continue
    return None


def build_expansion(index, base_case_path, config, cases_root, *, cancel=lambda:False, progress=lambda value:None):
    started=time.perf_counter();report=None
    base=load_case(base_case_path)
    try:
        report=_preview(index,base,base_case_path,config,cancel,progress)
        report['status']='building';report['completed_levels']=0
        for item in report['levels']:item['status']='not_run'
        if not report['build_allowed']:
            report['status']='failed';report['error']='Preflight resource limits prevent construction';return report
        root=Path(cases_root);root.mkdir(parents=True,exist_ok=True)
        available={item['level']:_reusable(root,item['content_key'],index.manifest['index_id']) for item in report['levels']}
        needed_disk=sum(item['estimates']['estimated_disk_bytes'] for item in report['levels'] if not available[item['level']])
        report['estimated_new_disk_bytes']=needed_disk
        if shutil.disk_usage(root).free<needed_disk:
            report['status']='failed';report['error']='Available disk is smaller than the sequence estimate';return report
        cfg=report['config']
        for item in report['levels']:
            if cancel():report['status']='cancelled';break
            progress(dict(phase='build',level=item['level'],level_count=len(report['levels']),node_count=item['node_count']))
            if cancel():item['status']='cancelled';report['status']='cancelled';break
            reuse=available[item['level']]
            if reuse:
                path,manifest=reuse;item.update(status='completed',reused=True,case_id=manifest['case_id'],case_path=str(path.resolve()))
                report['completed_levels']+=1;continue
            staging=root/('.scope-expansion-'+uuid4().hex)
            destination=root/('expanded-'+item['content_key'][:20])
            if destination.exists():
                report['status']='failed';item.update(status='failed',error='Destination exists but is not a complete matching scope');break
            try:
                level_cfg=dict(name=(base['manifest'].get('case_name','范围')+' · '+str(item['node_count']))[:100],
                               scope=dict(body_ids=item['body_ids'],hops=0,max_nodes=item['budget'],category='all'),groups=report['groups'])
                selection=copy.deepcopy(item['selection'])
                selection.update(expansion_base_case_id=report['identity']['base_case_id'],expansion_level=item['level'],
                                 retained_body_ids=report['base']['body_ids'] if item['level']==1 else report['levels'][item['level']-2]['body_ids'])
                write_selected_case(index,level_cfg,selection,staging,default_experiment=report['default_experiment'],
                                    scan_limit=cfg['scan_limit'],max_edges=cfg['max_internal_edges'],cancel=cancel)
                if cancel():raise InterruptedError('Scope publication cancelled')
                manifest=json.loads((staging/'manifest.json').read_text(encoding='utf-8'))
                # Publish only after every matrix/metadata file is present.
                staging.rename(destination)
                item.update(status='completed',reused=False,case_id=manifest['case_id'],case_path=str(destination.resolve()),
                            actual_disk_bytes=sum(p.stat().st_size for p in destination.iterdir() if p.is_file()))
                report['completed_levels']+=1
            except InterruptedError as error:
                item.update(status='cancelled',error=str(error));report['status']='cancelled';break
            except Exception as error:
                item.update(status='failed',error=str(error));report['status']='failed';break
            finally:
                if staging.exists():
                    # A cancelled staging directory must have no runnable
                    # manifest, even for glob-based legacy catalogues.
                    (staging/'manifest.json').unlink(missing_ok=True)
                    item['partial_directory']=str(staging.resolve())
        if report['status']=='building':report['status']='completed'
        return report
    except InterruptedError:
        if report is None:
            report=dict(kind='scope_expansion',schema_version=1,status='cancelled',config=copy.deepcopy(config),
                        identity=dict(base_case_id=base['manifest']['case_id'],source_index_id=index.manifest['index_id'],model_version=MODEL_VERSION),
                        base=dict(case_id=base['manifest']['case_id'],case_path=str(Path(base_case_path).resolve()),body_ids=[str(n['bodyId']) for n in base['nodes']]),
                        levels=[],completed_levels=0,error='Cancelled during preview')
        else:report['status']='cancelled'
        return report
    finally:
        close_case(base)
        if report is not None:report['elapsed_seconds']=time.perf_counter()-started


def save_expansion(root, report):
    validate_expansion(report)
    folder=Path(root)/('scope-expansion-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'scope-expansion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return folder


def validate_expansion(report):
    if not isinstance(report,dict) or report.get('kind')!='scope_expansion' or report.get('schema_version')!=1:
        raise ValueError('Unsupported saved expansion sequence')
    if report.get('status') not in ('preview','completed','cancelled','failed','building'):
        raise ValueError('Invalid expansion completion state')
    if report.get('identity',{}).get('model_version')!=MODEL_VERSION:
        raise ValueError('Saved expansion model identity does not match')
    identity=report.get('identity',{})
    if any(not isinstance(identity.get(key),str) or not identity[key] for key in ('base_case_id','source_index_id')):
        raise ValueError('Expansion requires saved scope and data-index identities')
    if report.get('base',{}).get('case_id')!=identity['base_case_id']:
        raise ValueError('Expansion base scope identity differs')
    previous=set(canonical_ids(report['base']['body_ids']));completed=0
    cfg=_config(report['config'],len(previous))
    if not isinstance(report['levels'],list) or len(report['levels'])>len(cfg['budgets']):
        raise ValueError('Saved expansion level count exceeds its definition')
    unfinished=False
    for number,item in enumerate(report['levels'],1):
        current=set(canonical_ids(item['body_ids']))
        if item['level']!=number or item['budget']!=cfg['budgets'][number-1] or len(current)>item['budget'] or not previous<=current or item['retained_node_count']!=len(previous) or item['added_node_count']!=len(current-previous) or item['node_count']!=len(current):
            raise ValueError('Saved expansion sequence is not exactly nested')
        if item['status']=='completed':
            if unfinished:raise ValueError('Completed expansion follows an unfinished level')
            completed+=1
            if not item.get('case_id') or not item.get('case_path'):raise ValueError('Completed expansion lacks saved scope identity')
        elif item['status'] not in ('preview','not_run','failed','cancelled'):
            raise ValueError('Invalid expansion level state')
        else:unfinished=True
        previous=current
    if 'completed_levels' in report and report['completed_levels']!=completed:
        raise ValueError('Saved expansion completion count differs')
    if report['status']=='completed' and completed!=len(cfg['budgets']):
        raise ValueError('Complete sequence contains missing or unfinished levels')
    return report


def load_expansion(path):
    path=Path(path);path=path/'scope-expansion.json' if path.is_dir() else path
    return validate_expansion(json.loads(path.read_text(encoding='utf-8')))
