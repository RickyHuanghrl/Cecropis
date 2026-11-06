"""Canonical identity of a bounded fixed task's numerical scope, not its index."""
import hashlib
import json

import numpy as np

RULES = dict(orientation='row=receiver,column=sender',
             contacts='positive-int64; duplicate directed contacts summed',
             normalization='float64 reciprocal(full-input-count) times contact count; zero denominator gives zero',
             denominator='all source records, including omitted and unannotated endpoints',
             eligibility='fixed-task explicit IDs; every scope member eligible',
             initial_state='all zeros', numeric='float64')
INTERPRETATION = 'positive integer aggregate contacts; duplicates summed; all records included in full input denominator'
KEYS = {'schema_version','algorithm','rules','components','digest','node_count','internal_edges','annotation_digest'}
COMPONENTS = {'members','directed_contacts','full_input_denominators','propagation_weights'}


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def validate_identity(value):
    if (not isinstance(value,dict) or set(value)!=KEYS or type(value.get('schema_version')) is not int or value.get('schema_version')!=1
            or value.get('algorithm')!='sha256-canonical-le64-v1'):
        raise ValueError('scope_content format/version is unsupported')
    if value['rules']!=RULES:
        raise ValueError('scope_content computation rules are incompatible')
    if not isinstance(value['components'],dict) or set(value['components'])!=COMPONENTS:
        raise ValueError('scope_content components are incomplete')
    for item in [value['digest'],value['annotation_digest'],*value['components'].values()]:
        if not isinstance(item,str) or len(item)!=64 or any(c not in '0123456789abcdef' for c in item):
            raise ValueError('scope_content requires SHA256 hexadecimal digests')
    for key in ('node_count','internal_edges'):
        if type(value[key]) is not int or value[key]<0:
            raise ValueError('scope_content invalid '+key)
    if value['digest']!=_digest({key:value[key] for key in ('schema_version','algorithm','rules','components','node_count','internal_edges')}):
        raise ValueError('scope_content digest does not match its declared components')
    return value


def content_identity(case, *, cancel=lambda:False, progress=lambda value:None):
    """Hash only saved scope arrays, in ID order and bounded numerical blocks.

    Actual propagation weights are checked as well as counts: a damaged saved
    weight array cannot silently pass using only its original contact table.
    No Python edge objects or complete-index data are materialized.
    """
    nodes=case['nodes']; ids=np.asarray([n['bodyId'] for n in nodes],dtype=np.int64)
    if len(set(map(int,ids)))!=len(ids) or np.any(ids<=0):
        raise ValueError('Scope members must be unique positive body IDs')
    order=np.argsort(ids); totals=np.asarray([n['total_input'] for n in nodes],dtype=np.int64)
    if np.any(totals<0):raise ValueError('Negative full input denominator')
    counts=case['counts']; matrix=case['matrix']
    if counts.shape!=(len(ids),len(ids)) or matrix.shape!=counts.shape:
        raise ValueError('Scope matrix dimensions do not match members')
    hashes={key:hashlib.sha256() for key in COMPONENTS}; annotation=hashlib.sha256()
    hashes['members'].update(ids[order].astype('<i8').tobytes())
    full=np.column_stack((ids[order],totals[order])).astype('<i8')
    hashes['full_input_denominators'].update(full.tobytes())
    edge_count=0
    for k,row in enumerate(order):
        if cancel():raise InterruptedError('Scope content verification cancelled')
        # One row is bounded by scope membership, never the complete index size.
        first,last=map(int,counts.indptr[row:row+2]); cols=counts.indices[first:last]
        data=np.asarray(counts.data[first:last]); sorted_row=np.argsort(ids[cols])
        if data.dtype.kind not in 'iu' or np.any(data<=0):
            raise ValueError('Scope directed contacts must be positive integers')
        if len(set(map(int,cols)))!=len(cols):raise ValueError('Scope duplicate edges were not aggregated')
        mfirst,mlast=map(int,matrix.indptr[row:row+2]); mcols=matrix.indices[mfirst:mlast]
        morder=np.argsort(ids[mcols]); weights=np.asarray(matrix.data[mfirst:mlast])[morder]
        expected=data[sorted_row].astype(np.float64)*(1./totals[row] if totals[row]>0 else 0.)
        if (not np.array_equal(ids[cols][sorted_row],ids[mcols][morder]) or
                not np.array_equal(weights,expected) or not np.all(np.isfinite(weights))):
            raise ValueError('Scope propagation weights do not match full-input normalization rules')
        if data.sum()>totals[row]:raise ValueError('Full input denominator is smaller than internal input')
        for start in range(0,len(cols),65536):
            stop=min(start+65536,len(cols)); loc=sorted_row[start:stop]
            block=np.empty((stop-start,3),dtype='<i8')
            block[:,0]=ids[row];block[:,1]=ids[cols[loc]];block[:,2]=data[loc]
            hashes['directed_contacts'].update(block.tobytes())
            # Endpoints are already bound by the contact stream and identical ordering.
            hashes['propagation_weights'].update(weights[start:stop].astype('<f8').tobytes())
        edge_count+=len(cols)
        annotation.update(json.dumps([str(ids[row]),{key:nodes[row].get(key) for key in
            ('type','name','instance','category','status')}],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()+b'\n')
        if k%256==0:progress(dict(phase='verify_scope_content',completed=k,total=len(ids)))
    result=dict(schema_version=1,algorithm='sha256-canonical-le64-v1',rules=dict(RULES),
                components={key:value.hexdigest() for key,value in hashes.items()},
                node_count=len(ids),internal_edges=edge_count)
    result['digest']=_digest(result);result['annotation_digest']=annotation.hexdigest()
    return result


def compare_identity(expected, actual):
    validate_identity(expected);validate_identity(actual)
    categories={'members':'scope members','directed_contacts':'internal directed connection counts',
                'full_input_denominators':'full input denominators','propagation_weights':'normalized propagation weights'}
    differences=[label for key,label in categories.items() if expected['components'][key]!=actual['components'][key]]
    if expected['rules']!=actual['rules']:differences.append('computation rules')
    return dict(matched=not differences and expected['digest']==actual['digest'],
                mismatch_categories=differences,annotation_difference=expected['annotation_digest']!=actual['annotation_digest'])


def source_data(manifest):
    # Provenance informs the user; compatibility requires numerical content, not a name alone.
    return dict(dataset_version=manifest.get('source_version') or 'unrecorded',record_interpretation=INTERPRETATION)
