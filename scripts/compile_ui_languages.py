"""Compile authored local translations; never contacts a translation service."""
from pathlib import Path
import argparse
import json
import re

ROOT = Path(__file__).resolve().parents[1] / 'cecropis'
LANGUAGES = ('zh-CN', 'en', 'ja', 'fr', 'de', 'es')


def compile_languages(*, check=False):
    messages = {}
    sources = sorted((ROOT/'locales/messages').glob('*.json'))
    if not sources:
        raise ValueError('No authored message files found')
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    for source in sources:
        for key, entry in json.loads(source.read_text(encoding='utf-8'), object_pairs_hook=unique_object).items():
            if key in messages:
                raise ValueError(f'{source.name}: duplicate message key: {key}')
            if set(entry) != set(LANGUAGES) or any(not isinstance(value,str) or not value.strip() for value in entry.values()):
                raise ValueError(f'{key}: six complete translations required')
            variables = [set(re.findall(r'\{(\w+)\}', value)) for value in entry.values()]
            if any(value != variables[0] for value in variables):
                raise ValueError(f'{key}: interpolation variables differ')
            messages[key] = entry
    outputs = {
        ROOT/'locales'/f'{code}.json':
        json.dumps({k:v[code] for k,v in messages.items()}, ensure_ascii=False, indent=2)+'\n'
        for code in LANGUAGES
    }
    payload = ('/* Generated from explicit local message keys; no DOM text matching. */\n'
               'window.UI_MESSAGES='+json.dumps(messages,ensure_ascii=False)+';\n')
    outputs[ROOT/'web/static/js/ui_messages.js'] = payload
    if check:
        stale = [str(path.relative_to(ROOT)) for path, content in outputs.items()
                 if not path.is_file() or path.read_text(encoding='utf-8') != content]
        if stale:
            raise ValueError('Generated messages are stale; run scripts/compile_ui_languages.py: '
                             + ', '.join(stale))
    else:
        for path, content in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
    return dict(keys=len(messages), languages=list(LANGUAGES))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='Check generated resources without rewriting them')
    print(json.dumps(compile_languages(check=parser.parse_args().check)))
