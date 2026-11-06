"""User-level location memory, using the existing version-1 workspace document."""
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from .workspace_config import load_workspace_config
from .configuration_store import write_json

DATA_FIELDS = {'index', 'cases', 'runs', 'raw', 'geometry', 'skeletons', 'skeleton_cache'}


def user_directory(*, platform=None, environ=None, home=None, data=False, legacy=False):
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    home = Path(home or Path.home())
    # An explicit process-local override supports isolated workstations/tests.
    override = (environ.get('MALECNS_LAB_CONFIG_HOME') if legacy else
                environ.get('CECROPIS_CONFIG_HOME') or environ.get('MALECNS_LAB_CONFIG_HOME'))
    if override:
        location=Path(override).expanduser()
        if not location.is_absolute():raise ValueError('Config home must be an absolute location')
        return location.resolve() / ('data' if data else 'settings')
    if platform == 'win32':
        base = Path(environ.get('LOCALAPPDATA') or environ.get('APPDATA') or home/'AppData'/'Local')
    elif platform == 'darwin':
        base = home/'Library'/'Application Support'
    else:
        candidate = environ.get('XDG_DATA_HOME' if data else 'XDG_CONFIG_HOME')
        base = Path(candidate) if candidate and Path(candidate).is_absolute() else home/('.local/share' if data else '.config')
    return base/('malecns-lab' if legacy else 'cecropis')


def binding_path():
    return user_directory()/'remembered-workspace.json'


def read_binding():
    path = binding_path()
    # Presence of the new record (including an invalid one) is authoritative.
    # A tombstone makes forgetting survive a legacy configuration fallback.
    if not path.exists() and not os.environ.get('CECROPIS_CONFIG_HOME'):
        path = user_directory(legacy=True)/'remembered-workspace.json'
    if not path.exists():
        return dict(status='missing', paths={})
    try:
        if path.stat().st_size > 65536:
            raise ValueError('Remembered binding exceeds 64 KiB')
        import json
        if json.loads(path.read_text(encoding='utf-8-sig')) == {'kind':'cecropis_binding_forgotten','version':1}:
            return dict(status='missing', paths={})
        paths = load_workspace_config(path)
        if set(paths) - DATA_FIELDS:
            raise ValueError('Remembered binding must not restore an experiment')
        return dict(status='saved', paths=paths)
    except (OSError, ValueError) as error:
        return dict(status='invalid', paths={}, detail=str(error))


def binding_status(paths=None):
    value = read_binding()
    return dict(status=value['status'], matches=bool(paths and value['status']=='saved' and
        value['paths']=={k:Path(v).expanduser().resolve() for k,v in paths.items() if k in DATA_FIELDS}),
        **({'detail':value['detail']} if 'detail' in value else {}))


@contextmanager
def _ownership():
    # Persistent lock inode; kernel releases ownership on process exit.
    path=binding_path(); path.parent.mkdir(parents=True, exist_ok=True)
    stream=path.with_suffix('.lock').open('a+b'); locked=False
    try:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        locked=True
        yield path
    finally:
        if locked:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        stream.close()


def remember_binding(paths):
    from .preparation import check_preparation, resolve_preparation_paths
    values={k:v for k,v in resolve_preparation_paths(paths).items() if k in DATA_FIELDS}
    if not check_preparation(values)['ready']:
        raise ValueError('Cannot remember an unavailable workspace')
    document=dict(kind='workspace_config',version=1,paths={k:str(v) for k,v in values.items()})
    with _ownership() as path:
        write_json(path,document,replace=True)
    return binding_status(values)


def forget_binding():
    with _ownership() as path:
        write_json(path,dict(kind='cecropis_binding_forgotten',version=1),replace=True)
    return dict(status='missing',matches=False)
