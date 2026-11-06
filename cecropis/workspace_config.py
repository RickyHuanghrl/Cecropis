"""Local workspace paths; task definitions never depend on these paths."""
import json
from pathlib import Path


PATH_FIELDS = {'index', 'cases', 'runs', 'case', 'geometry', 'raw', 'skeletons', 'skeleton_cache'}


def _path(value, base, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Workspace paths.{field} must be a nonempty path')
    try:path = Path(value).expanduser()
    except RuntimeError as error:raise ValueError(f'Workspace paths.{field}: {error}') from error
    return (path if path.is_absolute() else base / path).resolve()


def load_workspace_config(path):
    """Read paths relative to the configuration file, without creating directories."""
    path = _path(str(path),Path.cwd(),'workspace')
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise ValueError(f'Cannot read workspace configuration {path}: {error}') from error
    if not isinstance(data, dict) or set(data) - {'kind', 'version', 'paths'}:
        raise ValueError('Workspace configuration accepts only kind, version and paths')
    if data.get('kind') != 'workspace_config' or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('Workspace configuration requires kind=workspace_config and version=1')
    values = data.get('paths')
    if not isinstance(values, dict) or set(values) - PATH_FIELDS:
        raise ValueError('Workspace paths accepts index, cases, runs, optional case, geometry, raw, skeletons and skeleton_cache')
    missing = {'index', 'cases', 'runs'} - set(values)
    if missing:
        raise ValueError('Workspace paths missing: ' + ', '.join(sorted(missing)))
    return {key: _path(value, path.parent, key) for key, value in values.items()}


def resolve_workspace_paths(*, root, command, workspace=None, cwd=None, **explicit):
    """Explicit CLI paths use cwd; configured paths use the configuration parent."""
    cwd = Path(cwd or Path.cwd()).resolve()
    root = Path(root).resolve()
    if set(explicit) - PATH_FIELDS:
        raise ValueError('Unknown workspace path fields')
    configured = load_workspace_config(_path(str(workspace), cwd, 'workspace')) if workspace else {}
    if workspace:
        result = dict(configured)
    else:
        from .local_binding import read_binding, user_directory
        remembered = read_binding() if not any(v is not None for v in explicit.values()) else None
        result = dict(remembered['paths']) if remembered and remembered['status']=='saved' else {}
        storage=user_directory(data=True)/'workspace'
        result.setdefault('cases',storage/'cases')
        result.setdefault('runs',storage/'results')
        # No implicit index in the source tree, and no historical demo default.
        # Remembered locations never restore a case or an experiment.
    for key, value in explicit.items():
        if value is not None:
            result[key] = _path(str(value), cwd, key)
    return {key: result.get(key) for key in PATH_FIELDS}
