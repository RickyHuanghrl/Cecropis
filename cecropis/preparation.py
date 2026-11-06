"""Readonly local readiness and explicit reuse/build/configure operations.

No dependency imports on module load: the preparation script can report missing
packages. Checks read schemas, NPY headers/end pointers and SQLite metadata,
never a connection batch, hash or raw geometry directory.
"""
import importlib
import json
import os
import shutil
import sqlite3
import sys
import shlex
from pathlib import Path
from .workspace_config import PATH_FIELDS, _path, load_workspace_config

ROOT = Path(__file__).resolve().parents[1]
ANNOTATIONS = 'body-annotations-male-cns-v1.0-minconf-0.5.feather'
WEIGHTS = 'connectome-weights-male-cns-v1.0-minconf-0.5.feather'
FORMAT = 'malecns-global-index-v1'
STAGES = ('stage_pre.bin', 'stage_post.bin', 'stage_weight.bin')


def resolve_preparation_paths(values=None, *, workspace=None, cwd=None):
    """Same version-1 workspace; explicit paths resolve from cwd."""
    base = Path(cwd or Path.cwd()).resolve()
    result = load_workspace_config(_path(str(workspace), base, 'workspace')) if workspace else {}
    if values is not None and not isinstance(values,dict):raise ValueError('paths must be an object')
    for key, value in (values or {}).items():
        if key not in PATH_FIELDS:
            raise ValueError('Unknown workspace path: ' + key)
        if value is not None and not isinstance(value,(str,Path)):raise ValueError(key+': path must be a string')
        if value is not None and str(value).strip():
            result[key] = _path(str(value), base, key)
    return result


def _json(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Metadata exceeds 1 MiB')
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict):raise ValueError('Metadata must be a JSON object')
    return value


def _issue(code, **params):
    return dict(code=code, params=params)


def dependencies():
    result = []
    for name in ('numpy', 'scipy', 'pyarrow'):
        try:
            module = importlib.import_module(name)
            result.append(dict(name=name, available=True, version=getattr(module, '__version__', None)))
        except (ImportError, OSError, ValueError) as error:
            result.append(dict(name=name, available=False, detail=str(error)))
    return result


def _sqlite_header(path):
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        columns = {row[1] for row in connection.execute('PRAGMA table_info(nodes)')}
        if not {'bodyId', 'metadata', 'category'} <= columns:
            raise ValueError('annotations.sqlite missing nodes/bodyId/metadata/category')
        connection.execute('SELECT bodyId FROM nodes LIMIT 1').fetchone()
    finally:
        connection.close()


def inspect_index(path, deps):
    if path is None:
        return dict(status='missing', issues=[_issue('pathRequired', field='index')], can_resume=False)
    path = Path(path)
    if not path.exists():
        return dict(status='missing', issues=[], can_resume=False)
    if not path.is_dir():
        return dict(status='incompatible', issues=[_issue('notDirectory', path=str(path))], can_resume=False)
    marker = path / 'manifest.json'
    if not marker.is_file():
        # Look at at most one directory entry, never enumerate the complete tree.
        with os.scandir(path) as entries:
            nonempty = next(entries, None) is not None
        if not nonempty:
            return dict(status='missing', issues=[], can_resume=False)
        result = dict(status='partial', can_resume=False, issues=[])
        try:
            staging = _json(path / 'staging.json')
            rows = staging.get('source_rows')
            if type(rows) is not int or rows <= 0:
                raise ValueError('No completed source-scan row count')
            if any((path / name).stat().st_size != rows * 8 for name in STAGES):
                raise ValueError('Staging lengths do not match the completed scan')
            _sqlite_header(path / 'annotations.sqlite')
            result.update(can_resume=True, source_rows=rows, staged_bytes=rows * 24,
                          minimum_finalize_output_bytes=rows * 24)
        except (OSError, ValueError, KeyError, sqlite3.Error) as error:
            result['issues'].append(_issue('partialNotResumable', detail=str(error)))
        return result
    if not all(d['available'] for d in deps):
        return dict(status='unchecked', issues=[_issue('dependenciesMissing')], can_resume=False)
    try:
        import numpy as np
        manifest = _json(marker)
        rules=dict(format_version=FORMAT,source_version='MaleCNS v1.0 minconf=0.5',
                   orientation='incoming: row=post, column=pre; outgoing: row=pre, column=post',
                   normalization='Integer full incoming totals retained for every indexed node.')
        for field,expected in rules.items():
            if manifest.get(field)!=expected:
                raise ValueError(f'{field}: expected {expected!r}, found {manifest.get(field)!r}')
        n, edges, annotated = [manifest[k] for k in ('node_count','edge_count','annotated_record_count')]
        if any(type(v) is not int or v < 0 for v in (n, edges, annotated)) or not n or annotated > n or not manifest.get('index_id'):
            raise ValueError('Invalid index identity or counts')
        array_info = []
        definitions = [('ids', n, 'int64'), ('total_input', n, 'int64'),
                       ('total_output', n, 'int64'), ('annotated_positions', annotated, 'int64')]
        for direction in ('incoming','outgoing'):
            definitions += [(direction+'_data', edges, 'int64'),
                            (direction+'_indices', edges, 'index'),
                            (direction+'_indptr', n+1, 'index')]
        for name, size, kind in definitions:
            target = path / (name+'.npy')
            array = np.load(target, mmap_mode='r', allow_pickle=False)
            try:
                allowed = ('int32','int64') if kind == 'index' else (kind,)
                if array.shape != (size,) or str(array.dtype) not in allowed:
                    raise ValueError(name + ': unexpected array shape or dtype')
                if target.stat().st_size != array.offset + array.nbytes:
                    raise ValueError(name + ': unexpected file length')
                if name.endswith('_indptr') and (int(array[0]) != 0 or int(array[-1]) != edges):
                    raise ValueError(name + ': invalid CSR endpoints')
                array_info.append(dict(name=name, shape=list(array.shape), dtype=str(array.dtype), bytes=target.stat().st_size))
            finally:
                if getattr(array, '_mmap', None): array._mmap.close()
        _sqlite_header(path / 'annotations.sqlite')
        return dict(status='ready', can_resume=False, issues=[], index_id=manifest['index_id'],
                    source_version=manifest['source_version'], node_count=n,
                    annotated_record_count=annotated, category_counts=manifest.get('category_counts',{}),
                    edge_count=edges, arrays=array_info,
                    existing_bytes=sum(a['bytes'] for a in array_info)+(path/'annotations.sqlite').stat().st_size,
                    check='metadata, readonly headers and CSR endpoints; not a full content verification')
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        return dict(status='incompatible', can_resume=False, issues=[_issue('indexInvalid', detail=str(error))])


def inspect_raw(path, deps):
    if path is None:
        return dict(status='missing', files=[], issues=[_issue('pathRequired', field='raw')])
    raw = Path(path)
    if raw.exists() and not raw.is_dir():
        return dict(status='incompatible',files=[],issues=[_issue('notDirectory',path=str(raw))])
    provenance=raw.parent/(raw.name+'.download')/'source-metadata.json'
    if provenance.is_file():
        try:
            source=_json(provenance)
            if (source.get('dataset'),source.get('version'),source.get('confidence'),source.get('dataset_item')) != ('MaleCNS','v1.0','minconf=0.5','connectivity'):
                raise ValueError('Download provenance is not MaleCNS v1.0 minconf=0.5 connectivity')
        except (OSError,ValueError,TypeError,AttributeError) as error:
            return dict(status='incompatible',files=[],issues=[_issue('rawSchema',path=str(provenance),detail=str(error))])
    files, issues = [], []
    arrow_available = next(d['available'] for d in deps if d['name']=='pyarrow')
    for name, required in ((ANNOTATIONS, ('bodyId',)), (WEIGHTS, ('body_pre','body_post','weight'))):
        source = raw / name
        record = dict(name=name, path=str(source), status='missing')
        if not source.is_file():
            record['partial_present'] = any((raw/(name+suffix)).exists() for suffix in ('.partial','.part'))
            issues.append(_issue('rawMissing', path=str(source)))
        elif not arrow_available:
            record.update(status='unchecked', bytes=source.stat().st_size)
        else:
            try:
                import pyarrow as pa
                with pa.memory_map(str(source), 'r') as memory:
                    reader = pa.ipc.open_file(memory)
                    schema = reader.schema
                    missing = set(required)-set(schema.names)
                    if missing:
                        raise ValueError('Missing columns: '+', '.join(sorted(missing)))
                    if name == WEIGHTS:
                        invalid = [key for key in required if not pa.types.is_int64(schema.field(key).type)]
                        if invalid: raise ValueError('Expected int64: '+', '.join(invalid))
                    elif not pa.types.is_integer(schema.field('bodyId').type):
                        raise ValueError('bodyId must be an integer column')
                    if name == ANNOTATIONS and any(not key.replace('_','').isalnum() for key in schema.names):
                        raise ValueError('Unsupported annotation column identifier')
                    record.update(status='ready', bytes=source.stat().st_size,
                                  schema={key:str(schema.field(key).type) for key in required},
                                  record_batches=reader.num_record_batches)
            except (OSError, ValueError, KeyError) as error:
                record['status']='incompatible'
                issues.append(_issue('rawSchema', path=str(source), detail=str(error)))
        files.append(record)
    status = 'ready' if all(f['status']=='ready' for f in files) else 'incompatible' if any(f['status']=='incompatible' for f in files) else 'missing' if any(f['status']=='missing' for f in files) else 'unchecked'
    return dict(status=status, files=files, issues=issues, source_rows=None,
                check='Arrow file schema only; value/null validation happens during explicit build')


def check_preparation(paths):
    paths = {key:Path(value).expanduser().resolve() for key,value in paths.items() if value is not None}
    deps = dependencies()
    index, raw = inspect_index(paths.get('index'), deps), inspect_raw(paths.get('raw'), deps)
    issues = []
    for field in ('index','cases','runs'):
        if field not in paths: issues.append(_issue('pathRequired', field=field))
        elif paths[field].exists() and not paths[field].is_dir(): issues.append(_issue('notDirectory', path=str(paths[field])))
        else:
            parent=paths[field]
            while not parent.exists() and parent!=parent.parent:parent=parent.parent
            if not parent.is_dir():issues.append(_issue('notDirectory',path=str(parent)))
    for field in ('raw','cases','runs'):
        if field in paths and paths.get('index') == paths[field]: issues.append(_issue('directoryConflict', field=field))
    if paths.get('skeletons') and paths.get('skeleton_cache'):
        if paths['skeleton_cache'].is_relative_to(paths['skeletons']): issues.append(_issue('directoryConflict', field='skeleton_cache'))
    missing = [d['name'] for d in deps if not d['available']]
    if missing: issues.append(_issue('missingPackages', names=', '.join(missing)))
    ready = index['status']=='ready' and not issues
    can_build = index['status']=='missing' and raw['status']=='ready' and not issues
    can_resume = index.get('can_resume',False) and not issues
    next_action = 'configure' if ready else 'resume' if can_resume else 'build' if can_build else 'fix'
    disk = dict(free_bytes=None, staging_bytes=index.get('staged_bytes'),
                peak_bytes=None, final_bytes=None, elapsed_prediction=None,
                basis='24 bytes/source row staging; two CSR directions retain int64 counts and indices. Peak also depends on unique IDs, temporary maps and SQLite; raw bytes are not a peak estimate.')
    if paths.get('index'):
        parent = paths['index']
        while not parent.exists() and parent != parent.parent: parent=parent.parent
        try:disk['free_bytes']=shutil.disk_usage(parent).free
        except OSError:pass
    if ready:disk['final_bytes']=index['existing_bytes']
    optional = dict(skeletons_available=bool(paths.get('skeletons') and (paths['skeletons']/'info').is_file()),
                    skeletons_required=False, geometry_processing='explicit only')
    return dict(kind='local_preparation', version=1, ready=ready, can_build=can_build,
                can_resume=can_resume, next_action=next_action, paths={k:str(v) for k,v in paths.items()},
                dependencies=deps, index=index, raw=raw, issues=issues, disk=disk, optional=optional)


def write_workspace(paths, output):
    """Explicit, idempotent write; never overwrite a different configuration."""
    report = check_preparation(paths)
    if not report['ready']: raise ValueError('Workspace is not ready; inspect preparation issues before configuring')
    output=Path(output).expanduser().resolve()
    document=dict(kind='workspace_config',version=1,paths=report['paths'])
    if output.exists():
        if load_workspace_config(output) == {k:Path(v).resolve() for k,v in document['paths'].items()}:
            return dict(path=str(output), reused=True, preparation=report)
        raise FileExistsError('Configuration exists with different paths; choose another output file')
    from .configuration_store import write_json
    try:
        write_json(output,document)
    except FileExistsError:
        if load_workspace_config(output)=={k:Path(v) for k,v in document['paths'].items()}:
            return dict(path=str(output),reused=True,preparation=report)
        raise
    return dict(path=str(output), reused=False, preparation=report)


def workspace_binding(paths, output):
    """Readonly configuration match; a planned filename is not a saved file."""
    if not output or not Path(output).expanduser().exists():return dict(status='missing')
    try:
        expected={key:Path(value).resolve() for key,value in paths.items() if value is not None}
        return dict(status='matched' if load_workspace_config(output)==expected else 'different')
    except (OSError,ValueError,TypeError):return dict(status='incompatible')


def prepare_local(paths, *, action, output=None, batch_size=65536, progress=None):
    """Explicit build/resume invokes exactly the existing processing engine."""
    if action not in ('build','resume','configure'):raise ValueError('Unknown preparation action')
    if type(batch_size) is not int or batch_size<=0:raise ValueError('batch_size must be a positive integer')
    report=check_preparation(paths)
    reused=report['ready']
    if not reused:
        if action=='build' and report['can_build']:
            from .global_index import build_global_index
            if progress:progress(dict(phase='source_scan',source_rows=0))
            build_global_index(paths['raw'],paths['index'],batch_size,progress)
        elif action=='resume' and report['can_resume']:
            from .global_index import resume_global_index
            resume_global_index(paths['index'],None,batch_size,progress)
        else:
            return dict(status='blocked',preparation=report)
    report=check_preparation(paths)
    if not report['ready']:return dict(status='blocked',preparation=report)
    if progress and not reused:progress(dict(phase='complete',node_count=report['index']['node_count']))
    result=dict(status='ready', index_reused=reused, preparation=report)
    if output:result['workspace']=write_workspace(paths,output)
    return result


def startup_commands(paths, output=None, *, python=None, port=8501, shell='auto'):
    if shell=='auto':shell='powershell' if os.name=='nt' else 'posix'
    if shell not in ('powershell','posix'):raise ValueError('shell must be auto, powershell or posix')
    quote=(lambda value:"'"+str(value).replace("'","''")+"'") if shell=='powershell' else (lambda value:shlex.quote(str(value)))
    executable=Path(python or sys.executable).expanduser().resolve()
    invoke='& ' if shell=='powershell' else ''
    prefix=invoke+quote(executable)+' -B -X utf8 '+quote(ROOT/'scripts/prepare_data.py')
    args=' '.join('--'+key.replace('_','-')+' '+quote(value) for key,value in paths.items() if value is not None)
    out=' --output '+quote(Path(output).expanduser().resolve()) if output else ''
    commands={action:prefix+' '+action+' '+args+(out if action!='check' else '') for action in ('check','build','resume','configure')}
    # Absolute script/executable paths work from a different current directory.
    if output:
        commands['launch']=('Set-Location -LiteralPath ' if shell=='powershell' else 'cd ')+quote(ROOT)+'\n'+invoke+quote(executable)+' -B -X utf8 -m cecropis --workspace '+quote(Path(output).expanduser().resolve())+' serve --port '+str(int(port))
    if paths.get('raw'):
        commands['download']=invoke+quote(executable)+' -B '+quote(ROOT/'scripts/download_data.py')+' start --dataset connectivity --target '+quote(paths['raw'])
    return commands


def powershell_commands(paths, output=None, **options):
    """Compatibility name for explicit PowerShell generation."""
    return startup_commands(paths,output,shell='powershell',**options)
