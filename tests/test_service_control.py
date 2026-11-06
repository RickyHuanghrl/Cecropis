"""Service lifecycle checks with tiny local fixtures; no model propagation."""
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from cecropis.service_control import ServiceControl, control_service, service_path, startup_message

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class ServiceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cecropis-service-')
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, CECROPIS_CONFIG_HOME=str(self.root / 'settings'))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_banner_only_on_interactive_streams(self):
        for stdout_tty, stderr_tty, enabled in [(True, True, True), (False, True, True),
                                               (True, False, True), (True, True, False)]:
            output = io.StringIO()
            with redirect_stderr(output), patch.object(output, 'isatty', return_value=stderr_tty), \
                    patch('sys.stdout.isatty', return_value=stdout_tty), \
                    patch('shutil.get_terminal_size', return_value=os.terminal_size((80, 24))):
                startup_message(8501, banner=enabled)
            self.assertEqual('___' in output.getvalue(), stdout_tty and stderr_tty and enabled)
            self.assertIn('http://127.0.0.1:8501/', output.getvalue())

    def test_corrupt_record_does_not_prevent_cleanup(self):
        control = ServiceControl(Mock(), 8501, lambda: True)
        control.path.parent.mkdir(parents=True)
        control.path.write_text('{broken', encoding='utf-8')
        output = io.StringIO()
        with redirect_stderr(output):
            control.close()
        self.assertIn('Could not clean', output.getvalue())
        self.assertTrue(control.path.exists())
        with self.assertRaises(ValueError):
            control_service(8501)

    def test_stop_waits_for_listener_release_after_record_removal(self):
        # Record removal precedes socket closure to avoid deleting a new owner's
        # record. The client must not report success in that short interval.
        record = {'instance': 'a' * 32}
        reply = {'kind': 'cecropis_service', 'port': 8501, 'status': 'running'}
        with patch('cecropis.service_control._read_record', side_effect=[record, None, None]), \
                patch('cecropis.service_control._request', return_value=reply), \
                patch('cecropis.service_control.time.sleep'), \
                patch('cecropis.service_control.socket.create_connection',
                      side_effect=[OSError('still closing'), ConnectionRefusedError()]) as connect:
            self.assertEqual(control_service(8501, stop=True)['status'], 'stopped')
        self.assertEqual(connect.call_count, 2)

    def test_control_auth_busy_and_foreign_identity(self):
        busy = [True]
        class Handler(BaseHTTPRequestHandler):
            def reply(self, status, data):
                payload = json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def do_GET(self):
                control.handle(self)
            def do_POST(self):
                control.handle(self)
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(server.server_close)
        port = server.server_address[1]
        def stop_idle():
            if busy[0]:
                return False
            control.stopping = True
            return True
        control = ServiceControl(server, port, stop_idle)
        with redirect_stderr(io.StringIO()):
            control.publish(banner=False)
        def run():
            try:
                server.serve_forever(poll_interval=.05)
            finally:
                control.close()
                server.server_close()
        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertEqual(control_service(port)['status'], 'running')
            for headers in [{}, {'X-Cecropis-Control':control.record['token'], 'Origin':'http://evil.example'}]:
                client = HTTPConnection('127.0.0.1', port)
                client.request('POST', '/api/service/stop', headers=headers)
                response = client.getresponse()
                response.read()
                client.close()
                self.assertEqual(response.status, 403)
            with self.assertRaisesRegex(ValueError, 'busy'):
                control_service(port, stop=True)
            saved = dict(control.record, instance='0'*32)
            service_path(port).write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                control_service(port, stop=True)
            self.assertTrue(worker.is_alive())
            service_path(port).write_text(json.dumps(control.record))
            busy[0] = False
            self.assertEqual(control_service(port, stop=True)['status'], 'stopped')
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        finally:
            if worker.is_alive():
                server.shutdown()
                worker.join(timeout=5)
            server.server_close()

    def test_real_cli_start_binding_transition_stop_and_restart(self):
        from tests.test_preparation import PreparationChecks
        from cecropis.preparation import prepare_local
        paths = PreparationChecks().fixture(self.root)
        prepare_local(paths, action='build', output=self.root/'workspace.json', batch_size=2)
        port = free_port()
        def cli(*args):
            return subprocess.run([sys.executable, '-B', '-m', 'cecropis', *args], cwd=ROOT,
                                  capture_output=True, text=True, encoding='utf-8', timeout=20)
        startup_timeout = 60
        startup_script = (
            "import faulthandler, runpy\n"
            "faulthandler.dump_traceback_later(45)\n"
            "try:\n"
            "    runpy.run_module('cecropis', run_name='__main__')\n"
            "finally:\n"
            "    faulthandler.cancel_dump_traceback_later()\n"
        )
        for iteration in range(2):
            # A file avoids pipe-buffer stalls and retains startup diagnostics.
            log = tempfile.TemporaryFile()
            self.addCleanup(log.close)
            child = subprocess.Popen([sys.executable, '-B', '-c', startup_script,
                                      'start', '--port', str(port), '--no-banner'],
                                     cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic()+startup_timeout
                while not service_path(port).exists():
                    if child.poll() is not None:
                        self.fail(f'service exited before registering (exit {child.returncode})')
                    if time.monotonic()>deadline:
                        self.fail(f'service did not register within {startup_timeout}s')
                    time.sleep(.05)
                self.assertEqual(json.loads(cli('status','--port',str(port)).stdout)['status'], 'running')
                if iteration == 0:
                    client = HTTPConnection('127.0.0.1', port)
                    client.request('GET','/')
                    markup=client.getresponse().read().decode()
                    client.close()
                    import re
                    initial=json.loads(re.search(r'window.preparationInitial=(.*?);</script>',markup)[1])
                    client=HTTPConnection('127.0.0.1',port)
                    client.request('POST','/api/preparation/open',json.dumps({'paths':{k:str(v) for k,v in paths.items()}}),
                                   {'X-Local-Token':initial['token'],'Content-Type':'application/json'})
                    response=client.getresponse()
                    self.assertEqual(response.status,200,response.read())
                    client.close()
                    deadline=time.monotonic()+startup_timeout
                    while True:
                        try:
                            client=HTTPConnection('127.0.0.1',port,timeout=1)
                            client.request('GET','/')
                            markup=client.getresponse().read().decode()
                            client.close()
                            if 'id="global_panel"' in markup:
                                break
                        except (OSError, HTTPException):
                            if time.monotonic()>deadline:
                                raise
                        finally:client.close()
                        if time.monotonic()>deadline:
                            self.fail('workspace did not open')
                        time.sleep(.05)
                    self.assertIn('<html lang="en">',markup)
                    self.assertNotIn('>分析<',markup)
                    # Verify that the live workbench serves the relocated assets,
                    # including the extracted classic script and worker.
                    for resource, mime in [('/workbench.js', 'text/javascript'),
                                           ('/skeleton_worker.js', 'text/javascript'),
                                           ('/workspace_shell.css', 'text/css')]:
                        client = HTTPConnection('127.0.0.1', port, timeout=3)
                        try:
                            client.request('GET', resource)
                            response = client.getresponse()
                            self.assertEqual(response.status, 200)
                            self.assertIn(mime, response.getheader('Content-Type'))
                            self.assertTrue(response.read())
                        finally:
                            client.close()
                stopped=cli('stop','--port',str(port))
                self.assertEqual(stopped.returncode,0,stopped.stderr)
                self.assertEqual(json.loads(stopped.stdout)['status'],'stopped')
                child.communicate(timeout=10)
                self.assertEqual(child.returncode,0)
                self.assertEqual(json.loads(cli('status','--port',str(port)).stdout)['status'],'not_running')
            finally:
                if child.poll() is None:
                    child.kill()  # Only this test's own child.
                child.communicate(timeout=10)
                if sys.exc_info()[0] is not None:
                    log.seek(0)
                    print(f'Service child output (iteration {iteration}):\n'
                          + log.read().decode('utf-8', errors='replace'), file=sys.stderr)
                log.close()


if __name__ == '__main__':
    unittest.main()
