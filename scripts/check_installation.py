"""Check an installed distribution from outside the source tree, without data.

Run with the target interpreter. This script deliberately does not add the
checkout to sys.path: missing wheel resources must not be masked by source files.
"""
import argparse
from html.parser import HTMLParser
from importlib import metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        key = {'script': 'src', 'link': 'href'}.get(tag)
        if key and key in attributes:
            self.paths.append(attributes[key])


class Response:
    def reply(self, status, payload, mime=None, cache=None):
        self.status, self.payload = status, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True,
                        help='Checkout that the imported package must not come from')
    parser.add_argument('--check-command', action='store_true',
                        help='Also require the installed cecropis command on PATH')
    args = parser.parse_args()
    import cecropis
    from cecropis import Lab, Workspace
    from cecropis.font_assets import FONT_ROOT, font_css, font_resource, font_status
    from cecropis.web_assets import WebAssets, template

    package = Path(cecropis.__file__).resolve().parent
    if package.is_relative_to(args.source_root.resolve()):
        raise RuntimeError('Source checkout is shadowing the installed distribution')
    distribution = metadata.distribution('cecropis')
    entries = [entry for entry in distribution.entry_points
               if entry.group == 'console_scripts' and entry.name == 'cecropis']
    if len(entries) != 1 or not callable(entries[0].load()):
        raise RuntimeError('Missing or invalid cecropis console entry point')
    if not callable(Lab) or not callable(Workspace):
        raise RuntimeError('Public Python API is unavailable')

    resources = set()
    for name, preparation in [('ui.html', False), ('preparation.html', True)]:
        assets = WebAssets(preparation=preparation)
        page = template(name).decode('utf-8')
        links = PageLinks()
        links.feed(page)
        for url in links.paths:
            response = Response()
            if not assets.reply(response, url) or response.status != 200 or not response.payload:
                raise RuntimeError(f'{name}: missing resource {url}')
            resources.add(url)
        if '<html lang="en">' not in page or 'Cecropis' not in page:
            raise RuntimeError(f'{name}: incorrect initial language or brand')
    if not all(font_status().values()) or not font_css():
        raise RuntimeError('Bundled font families are incomplete')
    for css in FONT_ROOT.glob('*/wght.css'):
        for relative in re.findall(r'url\([\'"]?([^\)\'\"]+)', css.read_text(encoding='utf-8')):
            resource = css.parent / relative
            url = '/assets/fonts/' + resource.relative_to(FONT_ROOT).as_posix()
            path, _ = font_resource(url)
            if not path.read_bytes():
                raise RuntimeError(f'Empty font: {url}')
            resources.add(url)
    for code in ('en', 'zh-CN', 'ja', 'fr', 'de', 'es'):
        messages = json.loads((package / 'locales' / (code + '.json')).read_text(encoding='utf-8'))
        if not messages:
            raise RuntimeError(f'Missing messages: {code}')

    # A temporary working directory prevents Python's current-directory import
    # behavior from accidentally finding the checkout in subprocess checks.
    commands = [[sys.executable, '-B', '-m', 'cecropis']]
    if args.check_command:
        commands.append(['cecropis'])
    with tempfile.TemporaryDirectory(prefix='cecropis-entry-') as directory:
        for command in commands:
            for options in (['--version'], ['--help'], ['start', '--help'], ['stop', '--help']):
                result = subprocess.run(command + options, cwd=directory,
                                        capture_output=True, text=True, timeout=30)
                if result.returncode or not result.stdout.strip():
                    raise RuntimeError(f'Entry failed: {command + options}\n{result.stderr}')
    print(json.dumps({'version': distribution.version, 'package': str(package),
                      'resources': len(resources), 'command_checked': args.check_command}))


if __name__ == '__main__':
    main()
