"""Loopback preparation status, independent of Lab and Workspace."""
import json
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse
from uuid import uuid4
from threading import Lock
from .web_assets import WebAssets, template
from .preparation import resolve_preparation_paths,check_preparation,write_workspace,workspace_binding
from .service_control import LocalRequestHandler


def settings_html(paths,token,output=None,*,back=False):
    initial=dict(paths={k:str(v) for k,v in paths.items()},output=str(output) if output else '',token=token,back=back)
    return template('preparation.html').decode('utf-8').replace('__PREPARATION_INITIAL__',
        json.dumps(initial,ensure_ascii=True).replace('<','\\u003c')).encode('utf-8')


def binding_operation(action,payload):
    from .local_binding import binding_status,remember_binding,forget_binding
    values=resolve_preparation_paths(payload.get('paths',{}))
    if action=='forget':
        return dict(memory=forget_binding()),None
    report=check_preparation(values)
    destination=payload.get('output') or None
    result=dict(preparation=report,configuration=workspace_binding(values,destination),memory=binding_status(values))
    if action=='open':
        if not report['ready']:
            raise ValueError('A compatible complete index is required')
        remember=payload.get('remember',False)
        if type(remember) is not bool:
            raise ValueError('remember must be a boolean')
        if remember:
            try:
                result['memory']=remember_binding(values)
            except (OSError,ValueError) as error:
                return dict(code='memorySaveFailed',detail=str(error)),None
        configuration=destination if result['configuration']['status']=='matched' else None
        return dict(opening=True,memory=result['memory']),dict(paths=values,configuration_path=configuration)
    if action=='configure':
        if not destination:
            raise ValueError('Choose a workspace JSON destination')
        result['workspace']=write_workspace(values,destination)
        result['configuration']=dict(status='matched')
    elif action!='check':
        raise ValueError('Unknown data settings operation')
    return result,None


def serve_preparation(paths,port=8501,output=None,*,banner=True,access_log=False):
    if type(port) is not int or not 1<=port<=65535:
        raise ValueError('port must be 1–65535')
    token=uuid4().hex
    chosen={}
    opening=Lock()
    html=settings_html(paths,token,output)
    assets = WebAssets(preparation=True)
    class Handler(LocalRequestHandler):
        def reply(self,status,data,mime='application/json; charset=utf-8',cache='no-store'):
            value=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(value)))
            self.send_header('Cache-Control',cache)
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(value)
        def allowed(self):
            host=self.headers.get('Host','')
            return host in ('127.0.0.1:'+str(port),'localhost:'+str(port)) and self.headers.get('Origin') in (None,'http://'+host)
        def do_GET(self):
            if control.handle(self):
                return
            if not self.allowed():
                self.reply(403,dict(code='localOnly'))
                return
            path=urlparse(self.path).path
            if path=='/':
                self.reply(200,html,'text/html; charset=utf-8')
                return
            if assets.reply(self, path):
                return
            self.reply(404,dict(code='notFound'))
        def do_POST(self):
            if control.handle(self):
                return
            if not self.allowed() or self.headers.get('X-Local-Token')!=token:
                self.reply(403,dict(code='localOnly'))
                return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=65536:
                    raise ValueError('Request size must be 1–65536 bytes')
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict):
                    raise ValueError('Request must be an object')
                if self.path not in ('/api/preparation/open','/api/preparation/check','/api/preparation/configure','/api/preparation/forget'):
                    self.reply(404,dict(code='notFound'))
                    return
                with opening:
                    if control.stopping:
                        self.reply(409,dict(code='opening'))
                        return
                    if chosen:
                        self.reply(409,dict(code='opening'))
                        return
                    result,binding=binding_operation(self.path.rsplit('/',1)[-1],payload)
                    self.reply(400 if result.get('code') else 200,result)
                    if binding:
                        chosen.update(binding)
                if binding:
                    server.shutdown()
            except (OSError,ValueError,KeyError,TypeError) as error:
                self.reply(400,dict(code='operationFailed',detail=str(error)))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    Handler.access_log = access_log
    from .service_control import ServiceControl

    def stop_if_idle():
        # Binding and shutdown cannot race to take ownership of this listener.
        if not opening.acquire(blocking=False):
            return False
        try:
            if chosen:
                return False
            control.stopping = True
            return True
        finally:
            opening.release()

    control = ServiceControl(server, port, stop_if_idle)
    from .process_signals import termination_as_interrupt
    try:
        control.publish(banner=banner)
        with termination_as_interrupt():
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        control.close()
        server.server_close()
    return chosen or None


def open_prepared_workspace(binding,port,*,banner=True,access_log=False):
    """Enter the existing workbench after the setup listener has released its port."""
    from .app import serve
    paths=binding['paths']
    return serve(case_path=paths.get('case'),port=port,run_root=paths['runs'],
                 index_path=paths['index'],cases_path=paths['cases'],
                 geometry_path=paths.get('geometry'),raw_path=paths.get('raw'),
                 skeleton_path=paths.get('skeletons'),skeleton_cache_path=paths.get('skeleton_cache'),
                 configuration_path=binding.get('configuration_path'),banner=banner,access_log=access_log)
