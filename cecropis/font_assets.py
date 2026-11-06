"""Restricted local font resources; no download or installation side effects."""
from pathlib import Path
import re
from urllib.parse import unquote

FONT_ROOT = Path(__file__).parent / 'web' / 'static' / 'assets' / 'fonts'


def font_status(root=FONT_ROOT):
    root = Path(root)
    entries = {'inter': 'inter/InterVariable.woff2', 'sc': 'noto-sans-sc/wght.css',
               'jp': 'noto-sans-jp/wght.css'}
    return {name: (root / relative).is_file() for name, relative in entries.items()}


def font_css(root=FONT_ROOT):
    """Reuse supplied package CSS and unicode ranges; absent assets aren't requested."""
    root = Path(root)
    rules, families = [], {'sc': 'sans-serif', 'jp': 'sans-serif'}
    for code, folder in [('sc', 'noto-sans-sc'), ('jp', 'noto-sans-jp')]:
        css = root / folder / 'wght.css'
        if css.is_file():
            source = css.read_text(encoding='utf-8')
            family = re.search(r'font-family:\s*[\'\"]([^\'\"]+)[\'\"]', source)
            if family:
                families[code] = repr(family.group(1))
                rules.append(f'@import url("/assets/fonts/{folder}/wght.css");')
    latin = 'sans-serif'
    if (root / 'inter' / 'InterVariable.woff2').is_file():
        rules.append('@font-face{font-family:Inter;src:url("/assets/fonts/inter/InterVariable.woff2") format("woff2");font-style:normal;font-weight:100 900;font-display:swap;}')
        latin = 'Inter'
    rules.append(f':root{{--font-latin:{latin};--font-sc:{families["sc"]};--font-jp:{families["jp"]};--font-cjk:var(--font-sc);--font-ui:var(--font-latin),var(--font-cjk),sans-serif;}}')
    rules.append(':lang(ja){--font-ui:var(--font-latin),var(--font-jp),sans-serif;font-family:var(--font-ui);} :lang(zh-CN){--font-ui:var(--font-latin),var(--font-sc),sans-serif;font-family:var(--font-ui);}')
    return '\n'.join(rules).encode('utf-8')


def font_resource(url_path, root=FONT_ROOT):
    root = Path(root).resolve()
    relative = unquote(url_path.removeprefix('/assets/fonts/'))
    if '\\' in relative or '..' in Path(relative).parts:
        raise ValueError('Invalid font resource path')
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise FileNotFoundError('Local font resource is missing')
    if len(Path(relative).parts) < 2 or Path(relative).parts[0] not in ('inter', 'noto-sans-sc', 'noto-sans-jp'):
        raise ValueError('Unknown font resource')
    mime = {'.woff2': 'font/woff2', '.css': 'text/css; charset=utf-8', '.txt': 'text/plain; charset=utf-8'}
    if target.stat().st_size > 16 * 1024**2:
        raise ValueError('Font resource exceeds size limit')
    if target.name in ('LICENSE', 'OFL'):
        return target, 'text/plain; charset=utf-8'
    if target.suffix not in mime or target.stat().st_size > 16 * 1024**2:
        raise ValueError('Unsupported font resource')
    return target, mime[target.suffix]
