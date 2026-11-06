"""Serve bundled browser resources without exposing the package directory."""
from pathlib import Path

from .font_assets import font_css, font_resource

WEB_ROOT = Path(__file__).parent / 'web'


def template(name: str) -> bytes:
    """Read one of the two application templates, never a request-supplied path."""
    if name not in ('ui.html', 'preparation.html'):
        raise ValueError('Unknown application template')
    return (WEB_ROOT / 'templates' / name).read_bytes()


class WebAssets:
    """Snapshot public scripts/styles at startup; fonts stay lazily loaded.

    URLs remain independent of the on-disk layout. Requests only look up exact
    entries in the snapshot, so source files and parent paths cannot be served.
    Both the preparation page and workbench use this resource boundary.
    """

    def __init__(self, *, preparation=False):
        names = {'preparation_ui.js', 'preparation.css', 'workspace_shell.css',
                 'ui_preferences.js', 'ui_messages.js'} if preparation else None
        self.files = {}
        for folder, extension, mime in (
            ('js', '*.js', 'text/javascript; charset=utf-8'),
            ('css', '*.css', 'text/css; charset=utf-8'),
        ):
            for path in sorted((WEB_ROOT / 'static' / folder).glob(extension)):
                if names is None or path.name in names:
                    self.files['/' + path.name] = (path.read_bytes(), mime)
        self.files['/assets/brand/favicon.svg'] = (
            (WEB_ROOT / 'static/assets/brand/favicon.svg').read_bytes(), 'image/svg+xml')

    def reply(self, handler, path: str) -> bool:
        """Return whether this request was consumed; caller validates local access."""
        if path in self.files:
            payload, mime = self.files[path]
            handler.reply(200, payload, mime)
        elif path == '/fonts.css':
            handler.reply(200, font_css(), 'text/css; charset=utf-8')
        elif path.startswith('/assets/fonts/'):
            try:
                resource, mime = font_resource(path)
                handler.reply(200, resource.read_bytes(), mime, 'public, max-age=86400')
            except (ValueError, OSError):
                handler.reply(404, {'code': 'missingResource'})
        else:
            return False
        return True
