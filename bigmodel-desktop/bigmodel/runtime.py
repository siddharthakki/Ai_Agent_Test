"""Official llama.cpp release bundles, including matching CUDA runtime libraries."""
import hashlib
from pathlib import Path
import re
import shutil
import urllib.request
import zipfile

from .core import request_json, safe_destination


def windows_builds():
    # /latest can be a source-only stable release. Find the newest binary release.
    releases = request_json('https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10')
    for release in releases:
        assets = release.get('assets', [])
        builds = []
        for a in assets:
            name = a['name']
            if not (name.startswith('llama-') and '-bin-win-' in name and name.endswith('-x64.zip')):
                continue
            if 'sycl' in name or 'openvino' in name:
                continue
            bundle = dict(a, dependencies=[])
            cuda = re.search(r'-cuda-([\d.]+)-', name)
            if cuda:
                dep_name = 'cudart-llama-bin-win-cuda-' + cuda[1] + '-x64.zip'
                dep = next((d for d in assets if d['name'] == dep_name), None)
                if not dep:
                    continue
                bundle['dependencies'] = [dep]
            builds.append(bundle)
        if builds:
            return sorted(builds, key=lambda b: ('cuda-12' not in b['name'], b['name']))
    raise ValueError('No compatible Windows binary release found. Choose an existing llama-server.exe.')


def install_bundle(bundle, root, cancel, progress):
    folder = Path(root) / Path(bundle['name']).stem
    folder.mkdir(parents=True, exist_ok=True)
    required = sum(a['size'] for a in [bundle] + bundle['dependencies'])
    if shutil.disk_usage(folder).free < required * 4:
        raise ValueError('Insufficient disk space for the runtime and matching libraries')
    exe = None
    for index, asset in enumerate([bundle] + bundle['dependencies']):
        archive = folder / (str(index) + '.zip.part')
        digest = hashlib.sha256()
        received = 0
        with urllib.request.urlopen(asset['browser_download_url'], timeout=45) as response, archive.open('wb') as out:
            while chunk := response.read(4 * 1024**2):
                if cancel.is_set():
                    raise InterruptedError('Runtime download stopped; retry to download again')
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                progress(f'{asset["name"]}: {received/1024**2:.0f} / {asset["size"]/1024**2:.0f} MiB')
        if received != asset['size']:
            raise ValueError('Incomplete runtime download')
        expected = asset.get('digest')
        if expected and expected != 'sha256:' + digest.hexdigest():
            raise ValueError('Runtime checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            if sum(e.file_size for e in z.infolist()) > shutil.disk_usage(folder).free:
                raise ValueError('Not enough disk space to extract runtime')
            for entry in z.infolist():
                if cancel.is_set():
                    raise InterruptedError('Runtime installation stopped')
                target = safe_destination(folder, entry.filename)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if index:
                    # Windows looks for CUDA DLLs beside the executable.
                    if target.suffix.lower() != '.dll':
                        continue
                    target = safe_destination(exe.parent, target.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(entry) as source, target.open('wb') as out:
                    shutil.copyfileobj(source, out)
        archive.unlink()
        if index == 0:
            exe = next(folder.rglob('llama-server.exe'), None)
            if not exe:
                raise ValueError('Archive does not contain llama-server.exe')
    return str(exe)
