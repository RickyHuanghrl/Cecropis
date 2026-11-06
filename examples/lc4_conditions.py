"""Bind a small example to your selected case; validate or write, never simulate."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cecropis import Lab, MODEL_VERSION
from cecropis.simulation import Experiment


def conditions_for_case(case_path, template_path=None):
    template_path = template_path or Path(__file__).with_name('lc4-run.json')
    template = json.loads(Path(template_path).read_text(encoding='utf-8'))
    experiment = Experiment.from_dict(template['experiment'])
    lab = Lab(case_path)
    try:
        experiment.validate(lab.case['nodes'])
        return dict(case_id=lab.case['manifest']['case_id'], model_version=MODEL_VERSION,
            conditions=[dict(name='unchanged', experiment=asdict(replace(experiment, gain=1.0))),
                        dict(name='attenuated', experiment=asdict(experiment))])
    finally:
        lab.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args(argv)
    if not args.preview and args.output is None:
        parser.error('writing requires --output; use --preview for a read-only check')
    try:
        document = conditions_for_case(args.case.expanduser())
        if args.preview:
            print(json.dumps(dict(document, preview=True), ensure_ascii=False))
        else:
            destination = args.output.expanduser()
            with destination.open('x', encoding='utf-8') as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            print(json.dumps(dict(output=str(destination.resolve()), case_id=document['case_id'])))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
