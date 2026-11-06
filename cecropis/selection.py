"""Saved analysis ranges and independent input/candidate/readout memberships."""
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy import sparse
from .case import normalize_counts


def canonical_ids(values):
    if not isinstance(values,(list,tuple)) or not values:
        raise ValueError('Choose a nonempty list of body IDs')
    if any(not isinstance(x,str) or not x.isascii() or not x.isdecimal() or str(int(x))!=x or int(x)<=0 or int(x)>np.iinfo(np.int64).max for x in values):
        raise ValueError('Body IDs must be canonical positive int64 strings')
    if len(set(values))!=len(values):raise ValueError('Body IDs must be unique')
    return sorted(values,key=int)


def select_scope(index,spec):
    allowed={'body_ids','seed_filter','hops','direction','max_nodes','category'}
    if not isinstance(spec,dict) or set(spec)-allowed:raise ValueError('Unknown scope fields')
    hops=spec.get('hops',0);limit=spec.get('max_nodes',500);direction=spec.get('direction','both');category=spec.get('category','neuron')
    if type(hops) is not int or not 0<=hops<=3:raise ValueError('Neighborhood hops must be 0..3')
    if type(limit) is not int or not 1<=limit<=200000:raise ValueError('Node limit must be 1..200000')
    if direction not in ('incoming','outgoing','both') or category not in ('neuron','glia','other','unannotated','all'):
        raise ValueError('Unknown neighborhood direction or record category')
    if bool(spec.get('body_ids'))==bool(spec.get('seed_filter')):raise ValueError('Choose body IDs or one annotation filter')
    if spec.get('seed_filter'):
        filters=dict(spec['seed_filter'])
        if category!='all':filters['category']=category
        seeds=canonical_ids([str(x) for x in index.ids_for(filters,max_count=limit)])
    else:seeds=canonical_ids(spec['body_ids'])
    if len(seeds)>limit:raise ValueError('Seed count exceeds the node limit; increase it explicitly')
    positions=np.searchsorted(index.ids,np.asarray(seeds,dtype=np.int64))
    if np.any(positions>=len(index.ids)) or np.any(index.ids[positions]!=np.asarray(seeds,dtype=np.int64)):
        raise ValueError('Unknown global body ID')
    excluded=None
    if hasattr(index,'ids_for'):
        if category=='unannotated':
            excluded=set(map(int,index.ids_for({'category':['neuron','glia','other']},max_count=len(index.ids))))
            eligible=None
        else:eligible=None if category=='all' else set(map(int,index.ids_for({'category':category},max_count=len(index.ids))))
    else:
        eligible=None if category=='all' else {int(b) for b,n in index.annotations.items() if n.get('category')==category}
    if (eligible is not None and any(int(b) not in eligible for b in seeds)) or (excluded is not None and any(int(b) in excluded for b in seeds)):
        raise ValueError('Seeds contain records outside the chosen category')
    selected=set(map(int,positions));frontier=sorted(selected);truncated=False;completed=0
    directions=('incoming','outgoing') if direction=='both' else (direction,)
    for step in range(hops):
        candidates={}
        for pos in frontier:
            for name in directions:
                matrix=getattr(index,name);start,stop=matrix.indptr[pos:pos+2]
                for neighbor,weight in zip(matrix.indices[start:stop],matrix.data[start:stop]):
                    j=int(neighbor)
                    if j not in selected and (eligible is None or int(index.ids[j]) in eligible) and (excluded is None or int(index.ids[j]) not in excluded):
                        candidates[j]=candidates.get(j,0)+int(weight)
        remaining=limit-len(selected)
        ranked=sorted(candidates,key=lambda j:(-candidates[j],int(index.ids[j])))
        frontier=ranked[:remaining];selected.update(frontier);completed=step+1
        if len(ranked)>remaining:truncated=True;break
        if not frontier:break
    ids=[str(index.ids[i]) for i in sorted(selected)]
    return dict(body_ids=ids,seed_ids=seeds,selected_node_count=len(ids),requested_hops=hops,hops_completed=completed,
                max_nodes=limit,direction=direction,category=category,truncated=truncated,
                selection_rule='breadth by hops; strongest accumulated neighbor counts first at node cap')


def _groups(nodes,groups,*,allow_empty_input=False):
    if not isinstance(groups,dict) or set(groups)!={'input','internal','output'}:
        raise ValueError('Define input, internal candidates and named output groups')
    selected={n['bodyId'] for n in nodes};parsed={}
    if any(not isinstance(labels,dict) or (not labels and not (role=='input' and allow_empty_input)) or len(labels)>100 for role,labels in groups.items()):
        raise ValueError('Expected named nonempty selection groups')
    reserved=set()
    for role in ('input','output'):
        for ids in groups.get(role,{}).values():
            if not isinstance(ids,(list,tuple)):raise ValueError('Input/output groups require explicit body IDs')
            reserved.update(ids)
    for role,labels in groups.items():
        if not isinstance(labels,dict) or (not labels and not (role=='input' and allow_empty_input)) or len(labels)>100:raise ValueError('Expected named nonempty selection groups')
        parsed[role]={}
        for label,ids in labels.items():
            if not isinstance(label,str) or not label.strip() or label=='__all__' or len(label)>80:
                raise ValueError('Group labels must be nonempty, at most 80 characters')
            values=sorted(selected,key=int) if ids=='__scope__' else (sorted(selected-reserved,key=int) if ids=='__remaining__' else canonical_ids(ids))
            if not values:raise ValueError('Selection group is empty')
            if not set(values)<=selected:raise ValueError(f'{role} group contains nodes outside the calculation scope')
            parsed[role][label]=values
    if not 1<=len(parsed['output'])<=32:raise ValueError('Define 1..32 distinct named output groups')
    membership_sets={role:{label:set(ids) for label,ids in labels.items()} for role,labels in parsed.items()}
    for n in nodes:
        n['memberships']={role:[label for label,ids in labels.items() if n['bodyId'] in ids] for role,labels in membership_sets.items()}
        n['role']=next((r for r in ('input','output','internal') if n['memberships'][r]),'context')
    return parsed


def _save_csr(folder,name,matrix):
    for key in ('data','indices','indptr'):
        np.save(folder/f'{name}_{key}.npy',getattr(matrix,key),allow_pickle=False)


def induced_stats(index, body_ids, *, scan_limit=5000000, max_edges=5000000, cancel=lambda: False):
    """Count all induced edges from bounded CSR row chunks, without row slicing."""
    ids = np.asarray(canonical_ids(body_ids), dtype=np.int64)
    positions = np.searchsorted(index.ids, ids)
    if np.any(positions >= len(index.ids)) or np.any(index.ids[np.minimum(positions, len(index.ids)-1)] != ids):
        raise ValueError('Unknown global body ID')
    incoming = index.incoming
    required = sum(int(incoming.indptr[p+1]-incoming.indptr[p]) for p in positions)
    if required > scan_limit:
        return dict(scan_complete=False, required_edges=required, scanned_edges=0,
                    internal_edges=None, internal_contacts=None, row_edges=None)
    row_edges = np.zeros(len(ids), dtype=np.int64)
    contacts = 0; total_edges = 0
    for row, pos in enumerate(positions):
        start, stop = map(int, incoming.indptr[pos:pos+2])
        for first in range(start, stop, 65536):
            if cancel():
                raise InterruptedError('Scope extraction cancelled')
            neighbors = incoming.indices[first:min(stop, first+65536)]
            local = np.searchsorted(positions, neighbors)
            mask = (local < len(positions)) & (positions[np.minimum(local, len(positions)-1)] == neighbors)
            row_edges[row] += int(mask.sum())
            contacts += int(incoming.data[first:min(stop, first+65536)][mask].sum())
        total_edges += int(row_edges[row])
        if total_edges > max_edges:
            raise MemoryError(f'Internal edges exceed max_internal_edges={max_edges}')
    return dict(scan_complete=True, required_edges=required, scanned_edges=required,
                internal_edges=int(row_edges.sum()), internal_contacts=contacts, row_edges=row_edges)


def induced_counts(index, body_ids, *, scan_limit=5000000, max_edges=5000000, cancel=lambda: False):
    """Allocate only the exact induced CSR, never all global input rows."""
    stats = induced_stats(index, body_ids, scan_limit=scan_limit, max_edges=max_edges, cancel=cancel)
    if not stats['scan_complete']:
        raise MemoryError(f"Induced-edge scan needs {stats['required_edges']} indexed edges; scan_limit={scan_limit}")
    ids = np.asarray(canonical_ids(body_ids), dtype=np.int64)
    positions = np.searchsorted(index.ids, ids)
    indptr = np.r_[0, np.cumsum(stats['row_edges'])].astype(np.int64)
    indices = np.empty(stats['internal_edges'], dtype=np.int32)
    data = np.empty(stats['internal_edges'], dtype=np.int64)
    incoming = index.incoming
    for row, pos in enumerate(positions):
        written = int(indptr[row])
        start, stop = map(int, incoming.indptr[pos:pos+2])
        for first in range(start, stop, 65536):
            if cancel():
                raise InterruptedError('Scope extraction cancelled')
            last = min(stop, first+65536)
            neighbors = incoming.indices[first:last]
            local = np.searchsorted(positions, neighbors)
            mask = (local < len(positions)) & (positions[np.minimum(local, len(positions)-1)] == neighbors)
            count = int(mask.sum())
            indices[written:written+count] = local[mask]
            data[written:written+count] = incoming.data[first:last][mask]
            written += count
    counts = sparse.csr_matrix((data, indices, indptr), shape=(len(ids), len(ids)))
    counts.sum_duplicates(); counts.sort_indices()
    return counts


def write_selected_case(index, config, selection, destination, *, counts=None, default_experiment=None,
                        scan_limit=5000000, max_edges=5000000, cancel=lambda: False):
    """Shared complete-case writer; caller controls staging and publication."""
    destination=Path(destination)
    if destination.exists():raise FileExistsError(f'Case exists; reopen it: {destination}')
    name=config.get('name')
    if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('Case name must contain 1..100 characters')
    ids=np.asarray(selection['body_ids'],dtype=np.int64);positions=np.searchsorted(index.ids,ids)
    if counts is None:
        counts=induced_counts(index,selection['body_ids'],scan_limit=scan_limit,max_edges=max_edges,cancel=cancel)
    totals_in=np.asarray(index.total_input[positions]);totals_out=np.asarray(index.total_output[positions])
    matrix=normalize_counts(counts,totals_in)
    metadata=index.nodes(selection['body_ids']) if hasattr(index,'nodes') else [index.node(b) for b in selection['body_ids']]
    nodes=[];inside_in=np.asarray(counts.sum(axis=1)).ravel();inside_out=np.asarray(counts.sum(axis=0)).ravel()
    for k,n in enumerate(metadata):
        n=dict(n);n['bodyId']=str(n['bodyId']);n.setdefault('type',None);n['index']=k
        n['group_label']=n.get('type') or n.get('instance') or ('body '+n['bodyId'])
        n.update(total_input=int(totals_in[k]),total_output=int(totals_out[k]),external_input=int(totals_in[k]-inside_in[k]),
                 external_output=int(totals_out[k]-inside_out[k]),internal_input_fraction=float(inside_in[k]/totals_in[k]) if totals_in[k] else 0.)
        nodes.append(n)
    no_input_protocol=isinstance(default_experiment,dict) and default_experiment.get('input_events')==[]
    groups=_groups(nodes,config['groups'],allow_empty_input=no_input_protocol)
    source_id=index.manifest.get('index_id','index-'+str(index.manifest.get('source_rows',0)))
    fingerprint=hashlib.sha256(json.dumps(dict(source=source_id,selection=selection,groups=groups),sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
    defaults=default_experiment if default_experiment is not None else dict(input_group=next(iter(groups['input'])),intervention_group=next(iter(groups['internal'])),outputs=list(groups['output']))
    manifest=dict(case_id='malecns-scope-'+fingerprint,case_name=name,case_kind='selection',source_index_id=source_id,
        source_graph_nodes=index.manifest.get('node_count'),source_graph_edges=index.manifest.get('edge_count'),
        source_annotated_records=index.manifest.get('annotated_record_count'),
        source_version='MaleCNS v1.0 minconf=0.5',source_url='https://male-cns.janelia.org/download/',
        source_files=index.manifest.get('source_files',[]),node_count=len(nodes),selection=selection,
        category_counts={cat:sum(n.get('category')==cat for n in nodes) for cat in ('neuron','glia','other','unannotated')},
        roles={role:sum(bool(n['memberships'][role]) for n in nodes) for role in groups},groups=groups,default_experiment=defaults,
        internal_contacts=int(counts.sum()),external_input_contacts=int((totals_in-inside_in).sum()),
        external_output_contacts=int((totals_out-inside_out).sum()),total_input_contacts=int(totals_in.sum()),
        scan={'internal_edges':counts.nnz},format='csr-arrays-v1',orientation='row=post, column=pre',
        normalization='Full source-table incoming counts, including every omitted record; fixed during intervention')
    destination.mkdir(parents=True)
    # JSON preserves flexible, nullable annotations and explicit memberships.
    (destination/'nodes.json').write_text(json.dumps(nodes,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    _save_csr(destination,'counts',counts);_save_csr(destination,'propagation',matrix)
    (destination/'case-selection.json').write_text(json.dumps(dict(config,selection_result=selection),ensure_ascii=False,indent=2),encoding='utf-8')
    if cancel():raise InterruptedError('Scope publication cancelled')
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return destination


def build_case(index,config,destination):
    if not isinstance(config,dict) or set(config)-{'name','scope','groups'}:raise ValueError('Expected name, scope and groups')
    # Preserve the old explicit case builder's available graph size; the new
    # progressive builder supplies its own preflight resource bounds.
    return write_selected_case(index,config,select_scope(index,config['scope']),destination,
                               scan_limit=int(index.incoming.nnz),max_edges=int(index.incoming.nnz))
