import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bigmodel.core import GIB, Hardware
from bigmodel.engine import Engine
from test_core import fixture


class SimulatedEngine(Engine):
    def inspect_runtime(self, runtime):
        self.help_text = '--api-key'
        return self.help_text

    def start(self, runtime, model, profile, timeout=900):
        self.check()
        self.current = profile
        if profile['name'] == 'broken':
            raise RuntimeError('out of memory')

    def benchmark(self, tokens=96):
        self.check()
        return {'prompt_tps':100, 'generation_tps':20, 'score_seconds':11.52}


class EngineTests(unittest.TestCase):
    def test_failed_candidate_not_selected_and_profile_invalidates(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            model, runtime = root/'m.gguf', root/'server.exe'
            fixture(model)
            runtime.write_bytes(b'runtime')
            engine = SimulatedEngine(root)
            plans = [{'name':'broken', 'context':2048}, {'name':'working', 'context':2048}]
            with patch('bigmodel.engine.candidates', return_value=plans), patch('bigmodel.engine.detect_hardware', return_value=Hardware(ram_available=8*GIB)):
                result = engine.optimize(runtime, model)
                self.assertEqual(result['winner']['profile']['name'], 'working')
                self.assertIn('error', result['results'][0])
                self.assertTrue(list((root/'profiles').glob('*.json')))
                engine.start_saved(runtime, model, 2048)
                model.write_bytes(model.read_bytes() + b'changed')
                with self.assertRaises(ValueError):
                    engine.start_saved(runtime, model, 2048)

    def test_cancel_does_not_save_winner(self):
        with tempfile.TemporaryDirectory() as d:
            engine = SimulatedEngine(d)
            engine.abort()
            with self.assertRaises(InterruptedError):
                engine.optimize('unused', 'unused')
            self.assertFalse((Path(d)/'profiles').exists())


if __name__ == '__main__':
    unittest.main()
