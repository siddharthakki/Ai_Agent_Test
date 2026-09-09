from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import threading
import time
import uuid
import urllib.request
import urllib.error

from .core import (CREATE_FLAGS, GIB, atomic_json, detect_hardware, gguf_metadata,
                   model_files, run)


def candidates(meta, size, hardware, help_text, context=2048, disk=False):
    if not 512 <= context <= min(meta['context'], 131072):
        raise ValueError(f'Context must be 512–{min(meta["context"], 131072)} for this model')
    usable_gpu = max(0, hardware.vram_free - 2 * GIB)
    usable_ram = max(0, hardware.ram_available - 4 * GIB)
    if size > usable_gpu + usable_ram and not disk:
        raise ValueError('Model exceeds estimated available GPU + RAM budget. Free memory, choose a smaller quant, '
                         'or explicitly enable experimental disk assistance.')
    blocks = meta['blocks']
    threads = max(1, hardware.threads // 2)
    base = {'context': context, 'threads': threads, 'batch': 512, 'ubatch': 128,
            'gpu_layers': 0, 'cpu_moe': None, 'mmap': disk, 'name': 'CPU baseline'}
    result = []
    if hardware.vram_total and usable_gpu:
        # These are starting estimates; only successful measured runs become profiles.
        fraction = min(1, usable_gpu / max(size, 1))
        layers = min(blocks + 1, max(0, int((blocks + 1) * fraction * .85)))
        for scale in (.7, 1.0):
            n = int(layers * scale)
            result.append(dict(base, name=f'Hybrid · {n} GPU layers', gpu_layers=n))
        if meta['experts'] > 0 and '--n-cpu-moe' in help_text:
            # Expert tensors dominate many MoE models, but not all. Keep estimates explicit.
            for ratio in (1.0, .85, .7):
                n = max(1, min(blocks, round(blocks * ratio)))
                estimate_ram = size * ratio * .9
                if disk or estimate_ram <= usable_ram:
                    result.append(dict(base, name=f'MoE hybrid · {n} CPU expert layers',
                                       gpu_layers=999, cpu_moe=n))
    if not result:
        result.append(base)
    if result and not disk:
        result.append(dict(result[-1], name=result[-1]['name'] + ' · memory mapped', mmap=True))
    unique = {}
    for p in result:
        unique.setdefault((p['gpu_layers'], p['cpu_moe'], p['mmap']), p)
    return list(unique.values())


def command(runtime, model, profile, help_text, port, key):
    args = [str(runtime), '-m', str(model), '-c', str(profile['context']),
            '-t', str(profile['threads']), '-tb', str(profile['threads']),
            '-b', str(profile['batch']), '-ub', str(profile['ubatch']),
            '-ngl', str(profile['gpu_layers']), '--host', '127.0.0.1',
            '--port', str(port), '--api-key', key, '-np', '1']
    if '--api-key' not in help_text:
        raise ValueError('This llama.cpp build is too old: API-key support is required.')
    if '--split-mode' in help_text:
        args += ['--split-mode', 'none', '--main-gpu', '0']
    if '--fit ' in help_text:
        args += ['--fit', 'off']
    if profile['cpu_moe'] is not None:
        if '--n-cpu-moe' not in help_text:
            raise ValueError('Runtime does not support CPU expert placement')
        args += ['--n-cpu-moe', str(profile['cpu_moe'])]
    if '--load-mode' in help_text:
        args += ['--load-mode', 'mmap' if profile['mmap'] else 'none']
    elif not profile['mmap']:
        args += ['--no-mmap']
    if '--cache-ram' in help_text:
        args += ['--cache-ram', '0']
    return args


class Engine:
    def __init__(self, root, progress=lambda _: None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.progress = progress
        self.cancel = threading.Event()
        self.process = None
        self.log = None
        self.lock = threading.RLock()
        self.port = None
        self.key = uuid.uuid4().hex
        self.help_text = ''

    def stop(self):
        with self.lock:
            p = self.process
            if p:
                if p.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'],
                                       capture_output=True, creationflags=CREATE_FLAGS)
                    else:
                        p.terminate()
                    try:
                        p.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait(timeout=5)
                self.process = None
            if self.log:
                self.log.close()
                self.log = None

    def abort(self):
        self.cancel.set()
        self.stop()

    def check(self):
        if self.cancel.is_set():
            raise InterruptedError('Stopped')

    def api(self, endpoint, body=None, timeout=180):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{endpoint}', data=data,
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': 'Bearer ' + self.key})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)

    def inspect_runtime(self, runtime):
        runtime = Path(runtime).resolve()
        if not runtime.is_file():
            raise ValueError('Choose an installed llama-server executable in Setup')
        self.help_text = run([str(runtime), '--help'])
        return self.help_text

    def start(self, runtime, model, profile, timeout=900):
        self.stop()
        self.check()
        self.active_context = profile['context']
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            self.port = s.getsockname()[1]
        self.key = uuid.uuid4().hex
        args = command(runtime, model, profile, self.help_text, self.port, self.key)
        with self.lock:
            self.check()
            self.log_path = self.root / ('server-' + uuid.uuid4().hex[:10] + '.log')
            self.log = self.log_path.open('w', encoding='utf-8')
            # No shell and no inherited llama configuration: the saved profile is authoritative.
            env = {k: v for k, v in os.environ.items() if not k.startswith('LLAMA_')}
            self.process = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT,
                                            creationflags=CREATE_FLAGS, env=env)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.check()
            if not self.process or self.process.poll() is not None:
                if self.process and self.process.returncode & 0xffffffff == 0xc0e90002:
                    raise RuntimeError('Windows blocked this runtime under its system integrity policy. '
                                       'Choose an existing approved installation in Setup.')
                raise RuntimeError('Runtime failed to load this configuration. See ' + self.log_path.name)
            h = detect_hardware()
            if h.ram_available and h.ram_available < 2 * GIB:
                self.stop()
                raise RuntimeError('Stopped to preserve at least 2 GiB of available system RAM')
            try:
                if self.api('/health', timeout=2).get('status') == 'ok':
                    self.progress('Model ready')
                    return
            except (OSError, ValueError, urllib.error.URLError):
                pass
            self.cancel.wait(1)
        self.stop()
        raise TimeoutError('Model did not become ready within 15 minutes')

    def guarded_api(self, endpoint, body):
        result, errors = [], []

        def worker():
            try:
                result.append(self.api(endpoint, body))
            except Exception as exc:
                errors.append(exc)
        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        while worker_thread.is_alive():
            self.check()
            h = detect_hardware()
            if h.ram_available and h.ram_available < 2 * GIB:
                self.stop()
                raise RuntimeError('Stopped because available system RAM fell below 2 GiB')
            worker_thread.join(.5)
        if errors:
            raise errors[0]
        self.check()
        return result[0]

    def benchmark(self, tokens=96):
        prompt = ('A local computer runs a language model using a graphics card and system memory. '
                  'Describe how memory bandwidth, available capacity, and context affect performance. ') * 12
        # Reserve generation space even for the smallest selectable context.
        while len(self.api('/tokenize', {'content': prompt}).get('tokens', [])) > self.active_context - tokens - 32:
            prompt = prompt[:len(prompt)//2]
            if not prompt:
                raise ValueError('Context is too small for the benchmark')
        result = self.guarded_api('/completion', {'prompt': prompt, 'n_predict': tokens,
                                  'temperature': 0, 'seed': 42, 'cache_prompt': False, 'ignore_eos': True})
        timings = result.get('timings', {})
        pp, tg = timings.get('prompt_per_second', 0), timings.get('predicted_per_second', 0)
        if pp <= 0 or tg <= 0 or timings.get('predicted_n', 0) < tokens:
            raise RuntimeError('Incomplete benchmark or missing runtime timings')
        return {'prompt_tps': pp, 'generation_tps': tg,
                'score_seconds': 512 / pp + 128 / tg}

    def fingerprint(self, runtime, model, context):
        files = model_files(model)
        stat = Path(runtime).stat()
        hw = detect_hardware()
        identity = {'runtime': str(Path(runtime).resolve()), 'runtime_size': stat.st_size,
                    'runtime_mtime': stat.st_mtime_ns, 'runtime_help': hashlib.sha256(self.help_text.encode()).hexdigest(),
                    'files': [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in files],
                    'gpu': hw.gpu_name, 'vram': hw.vram_total, 'threads': hw.threads, 'context': context}
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]

    def optimize(self, runtime, model, context=2048, disk=False):
        self.check()
        self.stop()
        self.inspect_runtime(runtime)
        files = model_files(model)
        metadata = gguf_metadata(files[0])
        hw = detect_hardware()
        plans = candidates(metadata, sum(p.stat().st_size for p in files), hw,
                           self.help_text, context, disk)
        key = self.fingerprint(runtime, model, context)
        results = []
        try:
            for index, profile in enumerate(plans):
                self.check()
                self.progress(f'Test {index + 1}/{len(plans)}: {profile["name"]}. Loading may take several minutes.')
                try:
                    self.start(runtime, model, profile)
                    self.benchmark(16)  # Warm-up is deliberately excluded from the score.
                    runs = [self.benchmark(), self.benchmark()]
                    measured = {k: statistics.median(r[k] for r in runs) for k in runs[0]}
                    results.append({'profile': profile, **measured})
                    self.progress(f'Measured: {measured["generation_tps"]:.2f} generation tok/s; '
                                  f'{measured["prompt_tps"]:.2f} prompt tok/s')
                except InterruptedError:
                    raise
                except Exception as exc:
                    results.append({'profile': profile, 'error': str(exc)})
                    self.progress('Configuration rejected: ' + str(exc))
                finally:
                    self.stop()
            successful = sorted((r for r in results if 'error' not in r), key=lambda r: r['score_seconds'])
            if not successful:
                raise RuntimeError('No candidate passed. Try a smaller context or quantization; logs are retained.')
            baseline = successful[0]['profile']
            refinements = []
            if 'threads' in baseline:
                refinements = [dict(baseline, name='Refine · fewer CPU threads',
                                    threads=max(1, baseline['threads'] * 2 // 3)),
                               dict(baseline, name='Refine · larger prompt batch', batch=2048, ubatch=256)]
                if baseline['cpu_moe']:
                    refinements.append(dict(baseline, name='Refine · more experts on GPU',
                                            cpu_moe=max(0, baseline['cpu_moe']-2)))
            for profile in refinements:
                self.check()
                self.progress(profile['name'])
                try:
                    self.start(runtime, model, profile)
                    self.benchmark(16)
                    runs = [self.benchmark(), self.benchmark()]
                    measured = {k: statistics.median(r[k] for r in runs) for k in runs[0]}
                    results.append({'profile': profile, **measured})
                    self.progress(f'Measured: {measured["generation_tps"]:.2f} generation tok/s; '
                                  f'{measured["prompt_tps"]:.2f} prompt tok/s')
                except InterruptedError:
                    raise
                except Exception as exc:
                    results.append({'profile': profile, 'error': str(exc)})
                finally:
                    self.stop()
            successful = sorted((r for r in results if 'error' not in r), key=lambda r: r['score_seconds'])
            # Validate the winner with a longer generation. Fall back if it is unstable.
            for winner in successful:
                self.check()
                try:
                    self.progress('Validating ' + winner['profile']['name'])
                    self.start(runtime, model, winner['profile'])
                    validation = self.benchmark(256)
                    saved = {'fingerprint': key, 'runtime': str(Path(runtime).resolve()),
                             'model': str(files[0]), 'hardware': asdict(hw), 'metadata': metadata,
                             'winner': winner, 'validation': validation, 'results': results,
                             'created': time.strftime('%Y-%m-%dT%H:%M:%S')}
                    atomic_json(self.root / 'profiles' / (key + '.json'), saved)
                    self.progress('Validated and saved. Model is running; open Chat to test it.')
                    return saved
                except InterruptedError:
                    raise
                except Exception as exc:
                    winner['validation_error'] = str(exc)
                    self.stop()
            raise RuntimeError('All candidates failed the longer validation run')
        except BaseException:
            self.stop()
            raise
        finally:
            atomic_json(self.root / 'last-benchmark.json', {'results': results})

    def start_saved(self, runtime, model, context):
        self.inspect_runtime(runtime)
        key = self.fingerprint(runtime, model, context)
        path = self.root / 'profiles' / (key + '.json')
        if not path.exists():
            raise ValueError('No validated profile for this model, runtime, GPU and context. Run Optimize first.')
        saved = json.loads(path.read_text(encoding='utf-8'))
        try:
            self.start(runtime, model, saved['winner']['profile'])
        except BaseException:
            self.stop()
            raise
        return saved
