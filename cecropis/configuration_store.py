"""Small configuration publication only; no data, jobs or dependency setup."""
import ctypes
import errno
import json
import os
import sys
from pathlib import Path
from uuid import uuid4


def publish_new(source, destination):
    """Atomically publish a complete file, refusing any existing destination."""
    if os.name == 'nt':
        os.rename(source, destination)  # Windows rename refuses an existing target.
        return
    try:
        os.link(source, destination)
        return
    except OSError as error:
        if error.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL):
            raise
    # Filesystems without hard links must still support exclusive publication.
    # Never fall back to a POSIX rename that could replace a concurrent writer.
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        function = libc.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    elif sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        function = libc.renamex_np
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        result = function(os.fsencode(source), os.fsencode(destination), 4)
    else:
        raise OSError(errno.ENOTSUP, 'Filesystem has no supported atomic no-replace publication')
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def write_json(path, document, *, replace=False):
    """replace=True is reserved for this user's dedicated remembered binding."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(document, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            publish_new(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
