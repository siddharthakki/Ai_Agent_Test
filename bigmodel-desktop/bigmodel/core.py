from __future__ import annotations

import csv
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict

GIB = 1024 ** 3
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def run(args, timeout=20):
    return subprocess.run(args, capture_output=True, text=True, errors='replace',
                          timeout=timeout, creationflags=CREATE_FLAGS, check=True).stdout


def request_json(url, body=None, timeout=30):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        'User-Agent': 'BigModelDesktop/0.1', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def data_dir():
    # A portable build keeps all user data beside the application.
    import sys
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    root = root / 'data'
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class Hardware:
    ram_total: int = 0
    ram_available: int = 0
    gpu_name: str = 'No NVIDIA GPU detected'
    vram_total: int = 0
    vram_free: int = 0
    threads: int = 1


def detect_hardware():
    h = Hardware(threads=os.cpu_count() or 1)
    if os.name == 'nt':
        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong) for n in ('total', 'available', 'page_total',
                                                'page_available', 'virtual_total', 'virtual_available', 'extended')]
        m = Memory()
        m.length = ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            h.ram_total, h.ram_available = m.total, m.available
    elif Path('/proc/meminfo').exists():
        values = {line.split(':')[0]: int(line.split()[1]) * 1024
                  for line in Path('/proc/meminfo').read_text().splitlines()}
        h.ram_total, h.ram_available = values['MemTotal'], values['MemAvailable']
    try:
        rows = list(csv.reader(run(['nvidia-smi', '--query-gpu=name,memory.total,memory.free',
                                   '--format=csv,noheader,nounits']).splitlines()))
        # The initial version targets GPU 0, rather than summing unusable aggregate VRAM.
        row = rows[0]
        h.gpu_name, h.vram_total, h.vram_free = row[0].strip(), int(row[1]) * 1024**2, int(row[2]) * 1024**2
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return h


def fit_label(size, hardware):
    if not size:
        return 'Size unknown — inspect before downloading'
    gpu = max(0, hardware.vram_free - 2 * GIB)
    ram = max(0, hardware.ram_available - 4 * GIB)
    if size <= gpu:
        return 'Likely GPU fit'
    if size <= gpu + ram:
        return 'GPU + RAM candidate' if gpu else 'CPU / RAM candidate'
    return 'Disk assistance needed — experimental / potentially very slow'


class HuggingFace:
    name = 'Hugging Face'

    def search(self, query):
        params = urllib.parse.urlencode({'search': query, 'filter': 'gguf', 'sort': 'downloads',
                                         'direction': '-1', 'limit': 35})
        return request_json('https://huggingface.co/api/models?' + params)

    def variants(self, repo):
        info = request_json('https://huggingface.co/api/models/' + urllib.parse.quote(repo, safe='/') + '?blobs=true')
        files = [f for f in info.get('siblings', []) if f['rfilename'].lower().endswith('.gguf')
                 and 'mmproj' not in f['rfilename'].lower()]
        groups = {}
        for f in files:
            name = f['rfilename']
            key = re.sub(r'-\d{5}-of-\d{5}(?=\.gguf$)', '', name)
            groups.setdefault(key, []).append(f)
        result = []
        for name, shards in groups.items():
            shards.sort(key=lambda f: f['rfilename'])
            split = re.search(r'-(\d{5})-of-(\d{5})\.gguf$', shards[0]['rfilename'])
            if split and (len(shards) != int(split[2]) or
                          [int(re.search(r'-(\d{5})-of-', x['rfilename'])[1]) for x in shards]
                          != list(range(1, int(split[2]) + 1))):
                continue
            sizes = [f.get('size') or f.get('lfs', {}).get('size', 0) for f in shards]
            result.append({'name': name, 'repo': repo, 'revision': info['sha'], 'files': shards,
                           'size': sum(sizes) if all(sizes) else 0,
                           'license': (info.get('cardData') or {}).get('license', 'See model card')})
        return sorted(result, key=lambda v: (v['size'] == 0, v['size']))


def safe_destination(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative:
        raise ValueError('Unsafe model filename')
    target = (Path(root) / p).resolve()
    if not target.is_relative_to(Path(root).resolve()):
        raise ValueError('Filename escapes download folder')
    return target


def verify_file(path, expected_size, sha256=None, cancel=None):
    if not expected_size or path.stat().st_size != expected_size:
        return False
    if sha256:
        digest = hashlib.sha256()
        with path.open('rb') as f:
            while chunk := f.read(8 * 1024**2):
                if cancel and cancel.is_set():
                    raise InterruptedError('Cancelled')
                digest.update(chunk)
        return digest.hexdigest() == sha256
    return True


def download_variant(variant, root, cancel, progress):
    root = Path(root) / variant['repo'].replace('/', '--') / variant['revision']
    root.mkdir(parents=True, exist_ok=True)
    if not variant['size']:
        raise ValueError('Download size is unknown. Choose a variant with published file sizes.')
    needed = 0
    for f in variant['files']:
        target = safe_destination(root, f['rfilename'])
        partial = target.with_suffix(target.suffix + '.part')
        size = f.get('size') or f.get('lfs', {}).get('size', 0)
        needed += max(0, size - (partial.stat().st_size if partial.exists() else 0)) if not target.exists() else 0
    if shutil.disk_usage(root).free < needed + GIB:
        raise ValueError('Not enough free disk space for all model shards plus 1 GiB reserve.')
    first = None
    for f in variant['files']:
        if cancel.is_set():
            raise InterruptedError('Download paused; partial files are kept for resume.')
        target = safe_destination(root, f['rfilename'])
        first = first or target
        target.parent.mkdir(parents=True, exist_ok=True)
        size = f.get('size') or f.get('lfs', {}).get('size', 0)
        sha = f.get('lfs', {}).get('sha256')
        if target.exists() and verify_file(target, size, sha, cancel):
            progress('Already verified: ' + target.name)
            continue
        partial = target.with_suffix(target.suffix + '.part')
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > size:
            partial.unlink()
            offset = 0
        if offset != size:
            url = ('https://huggingface.co/' + urllib.parse.quote(variant['repo'], safe='/') + '/resolve/'
                   + variant['revision'] + '/' + urllib.parse.quote(f['rfilename'], safe='/'))
            headers = {'User-Agent': 'BigModelDesktop/0.1'}
            if offset:
                headers['Range'] = f'bytes={offset}-'
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as response:
                if offset and response.status == 206:
                    if not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                        raise ValueError('Server returned an invalid resume offset')
                elif response.status == 200:
                    offset = 0
                else:
                    raise ValueError('Unexpected download response')
                with partial.open('ab' if offset else 'wb') as out:
                    while chunk := response.read(4 * 1024**2):
                        if cancel.is_set():
                            raise InterruptedError('Download paused; choose Download again to resume.')
                        out.write(chunk)
                        offset += len(chunk)
                        progress(f'{target.name}: {offset / GIB:.2f} / {size / GIB:.2f} GiB')
            progress('Verifying ' + target.name)
        if not verify_file(partial, size, sha, cancel):
            # A corrupt complete partial must not be reused forever.
            partial.unlink(missing_ok=True)
            raise ValueError('Download verification failed. Retry to fetch a clean copy.')
        partial.replace(target)
    return str(first)


def gguf_metadata(path):
    """Read bounded GGUF v2/v3 metadata without loading tensors or tokenizer arrays."""
    with Path(path).open('rb') as f:
        length = os.fstat(f.fileno()).st_size

        def read(n):
            if n < 0 or f.tell() + n > length:
                raise ValueError('Truncated GGUF')
            value = f.read(n)
            if len(value) != n:
                raise ValueError('Truncated GGUF')
            return value

        def number(fmt):
            return struct.unpack('<' + fmt, read(struct.calcsize('<' + fmt)))[0]

        def string(keep=True):
            n = number('Q')
            if n > length - f.tell():
                raise ValueError('Invalid GGUF string length')
            if keep:
                if n > 1024**2:
                    raise ValueError('GGUF metadata string too large')
                return read(n).decode('utf-8', errors='replace')
            f.seek(n, 1)

        formats = {0:'B', 1:'b', 2:'H', 3:'h', 4:'I', 5:'i', 6:'f', 7:'?', 10:'Q', 11:'q', 12:'d'}

        def value(kind, keep=True, depth=0):
            if depth > 2:
                raise ValueError('Nested metadata limit exceeded')
            if kind in formats:
                return number(formats[kind])
            if kind == 8:
                return string(keep)
            if kind == 9:
                subtype, count = number('I'), number('Q')
                if count > 10_000_000:
                    raise ValueError('GGUF array limit exceeded')
                if subtype in formats:
                    amount = count * struct.calcsize('<' + formats[subtype])
                    if amount > length - f.tell():
                        raise ValueError('Truncated GGUF array')
                    f.seek(amount, 1)
                else:
                    for _ in range(count):
                        value(subtype, False, depth + 1)
                return None
            raise ValueError('Unknown GGUF metadata type')

        if read(4) != b'GGUF' or number('I') not in (2, 3):
            raise ValueError('Choose a GGUF v2 or v3 model')
        number('Q')
        count = number('Q')
        if count > 100_000:
            raise ValueError('GGUF metadata limit exceeded')
        metadata = {}
        for _ in range(count):
            key = string()
            kind = number('I')
            keep = key.startswith('general.') or key.endswith(('.block_count', '.expert_count', '.context_length'))
            v = value(kind, keep)
            if keep:
                metadata[key] = v
        arch = metadata.get('general.architecture', '')
        blocks = int(metadata.get(arch + '.block_count', 0))
        if not 1 <= blocks <= 1024:
            raise ValueError('Missing or unsupported transformer block count in GGUF')
        return {'architecture': arch, 'blocks': blocks,
                'experts': int(metadata.get(arch + '.expert_count', 0)),
                'context': int(metadata.get(arch + '.context_length', 2048))}


def model_files(path):
    path = Path(path).resolve()
    match = re.match(r'^(.*)-(\d{5})-of-(\d{5})\.gguf$', path.name)
    if not match:
        if not path.is_file():
            raise ValueError('Model file does not exist')
        return [path]
    if int(match[2]) != 1:
        raise ValueError('Select the first shard (00001) of the split model')
    count = int(match[3])
    if not 1 <= count <= 1000:
        raise ValueError('Invalid shard count')
    files = [path.with_name(f'{match[1]}-{i:05d}-of-{count:05d}.gguf') for i in range(1, count + 1)]
    if not all(p.is_file() for p in files):
        raise ValueError('One or more model shards are missing')
    return files


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temp.replace(path)
