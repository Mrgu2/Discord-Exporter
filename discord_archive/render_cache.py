"""Verify both render inputs and published PNG bytes before reusing an export."""
import hashlib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


class ImageSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attributes):
        if tag == 'img':
            attributes = dict(attributes)
            self.sources.append(attributes.get('data-local-src') or attributes.get('src') or '')


def fingerprint(input_path, root):
    input_path,root = Path(input_path),Path(root)
    code = Path(__file__).resolve().parent.parent
    paths = [input_path,code/'scripts/render.mjs',code/'scripts/png.mjs',code/'web/manuscript.css',code/'web/reading.css']
    parser = ImageSources();parser.feed(input_path.read_text())
    digest = hashlib.sha256(b'native-2x-render-v1')
    for source in parser.sources:
        digest.update(source.encode())
        url = urlsplit(source)
        if url.scheme == 'data':
            continue
        if url.scheme not in ('','file') or url.netloc:
            return None
        path = unquote(url.path)
        paths.append(root/'data/media'/Path(path).name if path.startswith('/media/') else
            (Path(path) if url.scheme == 'file' else input_path.parent/path))
    try:
        for path in sorted(set(paths)):
            digest.update(str(path.absolute()).encode())
            digest.update(file_hash(path).encode())
    except OSError:
        return None
    return digest.hexdigest()


def receipt(result, output_path, signature):
    if not signature or not result.get('images'):
        return None
    files = []
    try:
        for path in result['images']:
            path = Path(output_path)/Path(path).name
            with path.open('rb') as handle:
                header = handle.read(24)
            if len(header) != 24 or header[:8] != b'\x89PNG\r\n\x1a\n':
                return None
            files.append({'file':path.name,'sha256':file_hash(path),'header':header.hex()})
    except OSError:
        return None
    return {'fingerprint':signature,'result':result,'files':files}


def reuse(entry, output_path, signature):
    if not signature or not entry or entry.get('fingerprint') != signature:
        return None
    result = entry.get('result')
    if not isinstance(result,dict) or not entry.get('files') or len(entry['files']) != len(result.get('images',[])):
        return None
    try:
        for item in entry['files']:
            if Path(item['file']).name != item['file']:
                return None
            path = Path(output_path)/item['file']
            with path.open('rb') as handle:
                header = handle.read(24)
            if header.hex() != item['header'] or file_hash(path) != item['sha256']:
                return None
    except (OSError,KeyError,TypeError):
        return None
    return result
