import hashlib
import io
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from bigmodel.core import (GIB, Hardware, HuggingFace, download_variant, fit_label,
                           gguf_metadata, model_files, safe_destination, verify_file, run)
from bigmodel.engine import candidates, command


def fixture(path):
    def text(s):
        b = s.encode()
        return struct.pack('<Q', len(b)) + b
    entries = [('general.architecture', 8, text('llama')),
               ('llama.block_count', 4, struct.pack('<I', 32)),
               ('llama.context_length', 4, struct.pack('<I', 4096)),
               ('tokenizer.ggml.tokens', 9, struct.pack('<IQ', 8, 2) + text('one') + text('two'))]
    raw = b'GGUF' + struct.pack('<IQQ', 3, 0, len(entries))
    for key, kind, value in entries:
        raw += text(key) + struct.pack('<I', kind) + value
    path.write_bytes(raw)


class CoreTests(unittest.TestCase):
    def test_windows_integrity_failure_is_actionable(self):
        with patch('bigmodel.core.subprocess.run', side_effect=subprocess.CalledProcessError(0xc0e90002, ['server'])):
            with self.assertRaisesRegex(RuntimeError, 'Windows blocked'):
                run(['server'])

    def test_gguf_reads_architecture_without_loading_token_array(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'm.gguf'
            fixture(path)
            self.assertEqual(gguf_metadata(path), {'architecture':'llama', 'blocks':32, 'experts':0, 'context':4096})
            path.write_bytes(path.read_bytes()[:-3])
            with self.assertRaises(ValueError):
                gguf_metadata(path)

    def test_paths_cannot_escape_download_folder(self):
        for p in ('../x', '/x', 'C:/x', 'a\\x', 'a/../../x'):
            with self.subTest(p=p), self.assertRaises(ValueError):
                safe_destination(Path.cwd(), p)

    def test_all_shards_required_and_first_only(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / 'model-00001-of-00002.gguf'
            b = Path(d) / 'model-00002-of-00002.gguf'
            a.touch()
            with self.assertRaises(ValueError):
                model_files(a)
            b.touch()
            self.assertEqual(model_files(a), [a.resolve(), b.resolve()])
            with self.assertRaises(ValueError):
                model_files(b)

    def test_combined_memory_recommendation(self):
        h = Hardware(ram_available=40*GIB, vram_free=20*GIB)
        self.assertEqual(fit_label(30*GIB, h), 'GPU + RAM candidate')
        self.assertIn('Disk', fit_label(90*GIB, h))
        self.assertIn('unknown', fit_label(0, h))

    def test_no_disk_without_opt_in(self):
        h = Hardware(ram_available=8*GIB, vram_free=4*GIB)
        m = {'blocks':32, 'experts':0, 'context':4096}
        with self.assertRaises(ValueError):
            candidates(m, 30*GIB, h, '', 2048)
        self.assertTrue(all(p['mmap'] for p in candidates(m, 30*GIB, h, '', 2048, True)))

    def test_moe_requires_runtime_support(self):
        h = Hardware(ram_available=64*GIB, vram_free=24*GIB, vram_total=24*GIB, threads=20)
        m = {'blocks':48, 'experts':512, 'context':4096}
        without = candidates(m, 60*GIB, h, '', 2048)
        self.assertTrue(all(p['cpu_moe'] is None for p in without))
        with_support = candidates(m, 60*GIB, h, '--n-cpu-moe', 2048)
        self.assertTrue(any(p['cpu_moe'] for p in with_support))

    def test_command_disables_fit_for_explicit_placement(self):
        p = {'context':2048, 'threads':10, 'batch':512, 'ubatch':128,
             'gpu_layers':999, 'cpu_moe':32, 'mmap':False}
        c = command('server.exe', 'model with spaces.gguf', p,
                    '--fit on --api-key --n-cpu-moe --load-mode', 1234, 'test-key')
        self.assertIn('model with spaces.gguf', c)
        self.assertEqual(c[c.index('--fit')+1], 'off')
        self.assertEqual(c[c.index('--load-mode')+1], 'none')
        self.assertEqual(c[c.index('--host')+1], '127.0.0.1')

    def test_group_shards_and_reject_incomplete_variants(self):
        info = {'sha':'abc', 'siblings':[
            {'rfilename':'Q4/m-00001-of-00002.gguf', 'size':10},
            {'rfilename':'Q4/m-00002-of-00002.gguf', 'size':20},
            {'rfilename':'Q8/m-00001-of-00002.gguf', 'size':40},
            {'rfilename':'mmproj.gguf', 'size':40}]}
        with patch('bigmodel.core.request_json', return_value=info):
            result = HuggingFace().variants('owner/model')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['size'], 30)
        self.assertEqual(result[0]['revision'], 'abc')

    def test_verification_rejects_corrupt_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'file'
            p.write_bytes(b'bad')
            self.assertFalse(verify_file(p, 3, hashlib.sha256(b'yes').hexdigest()))

    def test_resume_ignored_range_restarts_cleanly(self):
        content = b'complete model'
        sha = hashlib.sha256(content).hexdigest()
        variant = {'repo':'a/b', 'revision':'abc', 'size':len(content),
                   'files':[{'rfilename':'m.gguf', 'size':len(content), 'lfs':{'sha256':sha}}]}
        class Response(io.BytesIO):
            status = 200
            headers = {}
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / 'a--b' / 'abc'
            folder.mkdir(parents=True)
            (folder / 'm.gguf.part').write_bytes(b'wrongprefix')
            with patch('bigmodel.core.urllib.request.urlopen', return_value=Response(content)):
                result = download_variant(variant, d, threading.Event(), lambda _: None)
            self.assertEqual(Path(result).read_bytes(), content)

    def test_cancel_never_promotes_partial(self):
        with tempfile.TemporaryDirectory() as d:
            cancel = threading.Event()
            cancel.set()
            v = {'repo':'a/b', 'revision':'abc', 'size':5,
                 'files':[{'rfilename':'m.gguf', 'size':5}]}
            with self.assertRaises(InterruptedError):
                download_variant(v, d, cancel, lambda _: None)
            self.assertFalse((Path(d)/'a--b'/'abc'/'m.gguf').exists())


if __name__ == '__main__':
    unittest.main()
