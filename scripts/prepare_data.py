"""Check, reuse or explicitly prepare local data; no downloads or installs."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cecropis.preparation import (resolve_preparation_paths,check_preparation,
                                   prepare_local,startup_commands)


def stopped(code,detail,paths=None,output=None,shell='auto'):
    result=dict(status='interrupted' if code=='checkRetainedStaging' else 'blocked',code=code,detail=detail)
    if paths is not None:
        try:
            result['preparation']=check_preparation(paths)
            result['next_check']=startup_commands(paths,output,shell=shell)['check']
        except (OSError,ValueError,TypeError):pass
    print(json.dumps(result,ensure_ascii=False,allow_nan=False),file=sys.stderr)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Local data readiness and workspace preparation')
    parser.add_argument('action',choices=('check','configure','build','resume','serve','remember','forget'))
    parser.add_argument('--shell',choices=('auto','powershell','posix'),default='auto')
    parser.add_argument('--workspace',type=Path)
    for name in ('raw','index','cases','runs','skeletons','skeleton-cache','case','geometry'):
        parser.add_argument('--'+name,type=Path)
    parser.add_argument('--output',type=Path,help='Explicit workspace JSON destination')
    parser.add_argument('--batch-size',type=int,default=65536)
    parser.add_argument('--port',type=int,default=8501)
    args=parser.parse_args(argv)
    try:
        if args.action=='forget':
            from cecropis.local_binding import forget_binding
            print(json.dumps(forget_binding()));return 0
        paths=resolve_preparation_paths({name:getattr(args,name) for name in
            ('raw','index','cases','runs','skeletons','skeleton_cache','case','geometry')},workspace=args.workspace)
        output=(args.output or args.workspace)
        if output:output=output.expanduser().resolve()
        if args.action=='remember':
            from cecropis.local_binding import remember_binding
            print(json.dumps(remember_binding(paths),ensure_ascii=False));return 0
        if args.action=='configure' and output is None:
            raise ValueError('configure requires --output or --workspace')
        if args.action=='serve':
            from cecropis.workspace_config import resolve_workspace_paths
            paths={k:v for k,v in resolve_workspace_paths(root=Path(__file__).resolve().parents[1],command='serve',workspace=args.workspace,
                **{name:getattr(args,name) for name in ('raw','index','cases','runs','skeletons','skeleton_cache','case','geometry')}).items() if v is not None}
            from cecropis.preparation_app import serve_preparation,open_prepared_workspace
            if check_preparation(paths)['ready']:
                open_prepared_workspace(dict(paths=paths,configuration_path=output),args.port)
            else:
                binding=serve_preparation(paths,port=args.port,output=output)
                if binding:
                    open_prepared_workspace(binding, args.port, banner=False)
            return 0
        if args.action=='check':
            result=check_preparation(paths)
            result['commands']=startup_commands(paths,output,port=args.port,shell=args.shell)
            result['command_shell']=('powershell' if sys.platform=='win32' else 'posix') if args.shell=='auto' else args.shell
            print(json.dumps(result,ensure_ascii=False,allow_nan=False))
            return 0 if result['ready'] or result['can_build'] or result['can_resume'] else 2
        def progress(info):
            phase='scan' if info['phase']=='source_scan' else 'complete' if info['phase']=='complete' else 'organize'
            print(json.dumps(dict(info,stage=phase),ensure_ascii=False),file=sys.stderr,flush=True)
        result=prepare_local(paths,action=args.action,output=output,
                             batch_size=args.batch_size,progress=progress)
        result['commands']=startup_commands(paths,output,port=args.port,shell=args.shell)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0 if result['status']=='ready' else 2
    except KeyboardInterrupt:
        stopped('checkRetainedStaging','Interrupted; existing files are retained',locals().get('paths'),locals().get('output'),args.shell)
        return 130
    except (OSError,ValueError,KeyError,TypeError) as error:
        stopped('operationFailed',str(error),locals().get('paths'),locals().get('output'),args.shell)
        return 2


if __name__=='__main__':
    from cecropis.process_signals import termination_as_interrupt
    with termination_as_interrupt():raise SystemExit(main())
