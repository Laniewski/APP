"""Load model input from UTF-8 files; no interpretation or hardware dependencies."""
import json
from pathlib import Path

CONTEXT_DIR = Path(__file__).resolve().parents[2] / 'ai_context'


def load_json(name, context_dir=CONTEXT_DIR):
    return json.loads((Path(context_dir) / name).read_text(encoding='utf-8'))


def load_messages(request, context_dir=CONTEXT_DIR):
    if not isinstance(request, str) or not request.strip() or len(request) > 4000:
        raise ValueError('Opis musi zawierać od 1 do 4000 znaków.')
    root = Path(context_dir)
    sections = []
    for name in ('station_and_actions.json', 'output_schema.json'):
        sections.append(name + '\n' + json.dumps(load_json(name, root), ensure_ascii=False, separators=(',', ':')))
    for path in sorted((root / 'data').rglob('*')):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in {'.txt', '.md'} and path.name != 'README.md':
            sections.append('SOURCE: ' + path.relative_to(root / 'data').as_posix() + '\n' + path.read_text(encoding='utf-8'))
    sections.append((root / 'assistant_prompt.txt').read_text(encoding='utf-8'))
    return [{'role': 'system', 'content': '\n\n'.join(sections)}, {'role': 'user', 'content': request}]
