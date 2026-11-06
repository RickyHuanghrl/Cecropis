# SPDX-FileCopyrightText: 2026 Ziyu Huang
# SPDX-License-Identifier: Apache-2.0
"""Authenticated control of one loopback listener; never signal a stored PID."""
import hmac
import json
import os
import shutil
import socket
import sys
import tempfile
import time
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import uuid4

from .local_binding import user_directory


def service_path(port: int) -> Path:
    """Locate this user's control record, independently of any data workspace."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('port must be 1–65535')
    return user_directory() / 'services' / f'{port}.json'


def version() -> str:
    # Source execution must not report the version of a different installed copy.
    source = Path(__file__).resolve().parents[1] / 'pyproject.toml'
    if source.is_file():
        import tomllib
        project = tomllib.loads(source.read_text(encoding='utf-8')).get('project', {})
        if project.get('name') == 'cecropis':
            return project['version']
    from importlib.metadata import version as installed_version
    return installed_version('cecropis')


WORDMARK = r"""  ____                          _
 / ___|___  ___ _ __ ___  _ __ (_)___
| |   / _ \/ __| '__/ _ \| '_ \| / __|
| |__|  __/ (__| | | (_) | |_) | \__ \
 \____\___|\___|_|  \___/| .__/|_|___/
                         |_|"""


class LocalRequestHandler(BaseHTTPRequestHandler):
    """Keep successful access traffic opt-in; errors retain stderr diagnostics."""

    access_log = False

    def log_request(self, code='-', size='-'):
        if self.access_log or not str(code).isdigit() or int(code) >= 400:
            super().log_request(code, size)


def startup_message(port, *, banner=True):
    """Keep terminal decoration out of redirected and machine-readable output."""
    interactive = sys.stdout.isatty() and sys.stderr.isatty()
    if banner and interactive and shutil.get_terminal_size().columns > max(map(len, WORDMARK.splitlines())):
        print(WORDMARK, file=sys.stderr)
    print(f'Cecropis {version()} — http://127.0.0.1:{port}/', file=sys.stderr, flush=True)
    print(f'Press Ctrl+C to stop, or run: python -m cecropis stop --port {port}', file=sys.stderr, flush=True)


class ServiceControl:
    """One record per bound port, scoped to the current OS user's settings."""

    def __init__(self, server, port, stop_if_idle):
        self.server, self.port, self.stop_if_idle = server, port, stop_if_idle
        self.path = service_path(port)
        self.record = dict(kind='cecropis_service', version=1, port=port,
                           instance=uuid4().hex, token=uuid4().hex, pid=os.getpid())
        self.stopping = False

    def publish(self, *, banner=True):
        # Called only after bind succeeds. mkstemp gives owner-only POSIX permissions.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f'.{self.port}-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(self.record, stream)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        startup_message(self.port, banner=banner)

    def close(self):
        """Remove only our record while we still own the listening socket.

        A malformed/unwritable record must not prevent socket and dataset cleanup.
        The client also waits for port release before reporting a successful stop.
        """
        try:
            record = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(record, dict) and record.get('instance') == self.record['instance']:
                self.path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            print(f'Could not clean the local service record: {error}', file=sys.stderr)

    def handle(self, handler):
        """Consume only authenticated CLI control requests; leave UI routes alone."""
        if handler.path not in ('/api/service/status', '/api/service/stop'):
            return False
        expected_method = 'GET' if handler.path.endswith('/status') else 'POST'
        supplied_token = handler.headers.get('X-Cecropis-Control', '').encode('utf-8')
        allowed = (handler.command == expected_method and
                   handler.headers.get('Host') == f'127.0.0.1:{self.port}' and
                   handler.headers.get('Origin') is None and
                   hmac.compare_digest(supplied_token, self.record['token'].encode('ascii')))
        if not allowed:
            handler.reply(403, dict(error='Local service credentials required'))
            return True
        response = dict(kind='cecropis_service', instance=self.record['instance'],
                        port=self.port, status='stopping' if self.stopping else 'running')
        if expected_method == 'POST':
            if not self.stop_if_idle():
                handler.reply(409, dict(error='Service is busy. Finish, pause or cancel the active operation before stopping.'))
                return True
            response['status'] = 'stopping'
        try:
            handler.reply(200, response)
        finally:
            if expected_method == 'POST':
                # Request handler is a different thread from serve_forever.
                self.server.shutdown()
        return True


def _read_record(port):
    path = service_path(port)
    try:
        with path.open('rb') as stream:
            payload = stream.read(4097)
    except FileNotFoundError:
        # Shutdown may remove the record between successive client polls.
        return None
    if len(payload) > 4096:
        raise ValueError('Invalid local service record')
    record = json.loads(payload)
    if (not isinstance(record, dict) or record.get('kind') != 'cecropis_service' or
            record.get('version') != 1 or record.get('port') != port or
            any(not isinstance(record.get(k), str) or len(record[k]) != 32 for k in ('token', 'instance'))):
        raise ValueError('Invalid local service record; no process was stopped')
    return record


def _request(record, method, action):
    connection = HTTPConnection('127.0.0.1', record['port'], timeout=3)
    try:
        connection.request(method, '/api/service/' + action,
                           headers={'X-Cecropis-Control': record['token']})
        response = connection.getresponse()
        body = response.read(8193)
        if len(body) > 8192:
            raise ValueError('Unrecognized service response; no process was stopped')
        try:
            data = json.loads(body)
        except ValueError as error:
            raise ValueError('Unrecognized service response; no process was stopped') from error
        if not isinstance(data, dict):
            raise ValueError('Unrecognized service response; no process was stopped')
        if response.status != 200:
            raise ValueError(data.get('error', 'Service identity could not be verified'))
        if (data.get('kind') != 'cecropis_service' or data.get('instance') != record['instance'] or
                data.get('port') != record['port']):
            raise ValueError('Service identity changed; no process was stopped')
        return data
    finally:
        connection.close()


def control_service(port, *, stop=False):
    """Verify an instance over loopback, then optionally request an idle shutdown.

    The recorded PID is informational. Neither stale records nor failed requests
    authorize an OS signal or a force-kill of any process.
    """
    record = _read_record(port)
    absent = dict(kind='cecropis_service', port=port, status='not_running')
    if record is None:
        return absent
    try:
        result = _request(record, 'GET', 'status')
    except ConnectionRefusedError:
        return absent  # A stale record is never used to kill a potentially reused PID.
    except (OSError, HTTPException) as error:
        raise ValueError(f'Cannot verify Cecropis on port {port}: {error}') from error
    if not stop:
        return result
    try:
        _request(record, 'POST', 'stop')
    except (OSError, HTTPException) as error:
        raise ValueError(f'Could not confirm the stop request on port {port}: {error}') from error
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        current = _read_record(port)
        if current is not None and current['instance'] != record['instance']:
            return dict(result, status='stopped')
        if current is None:
            try:
                # Windows can take about a second to report a refused loopback
                # connection; a subsecond timeout would never confirm closure.
                with socket.create_connection(('127.0.0.1', port), timeout=3):
                    pass
            except ConnectionRefusedError:
                return dict(result, status='stopped')
            except OSError:
                pass  # An inaccessible listener is not proof that it has closed.
        time.sleep(.1)
    raise ValueError('Stop was requested, but shutdown has not completed. Check the service terminal; no force-kill was attempted.')
