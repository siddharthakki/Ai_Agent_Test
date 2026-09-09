from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class UITests(unittest.TestCase):
    def test_window_constructs_and_accepts_worker_events(self):
        try:
            import tkinter
            from bigmodel.app import App
        except ImportError:
            self.skipTest('Tk not installed')
        with tempfile.TemporaryDirectory() as d, patch('bigmodel.app.data_dir', return_value=Path(d)), patch.object(App, 'task'):
            try:
                app = App()
            except tkinter.TclError as exc:
                if 'display' in str(exc).lower():
                    self.skipTest('No graphical display')
                raise
            try:
                app.withdraw()
                self.assertEqual(len(app.tabs.tabs()), 4)
                app.events.put(('repos', [{'id':'example/model', 'downloads':10}]))
                app.pump()
                self.assertEqual(app.repo_tree.item('0')['values'][0], 'example/model')
                app.events.put(('inspection', '48 layers · hybrid candidate'))
                app.pump()
                self.assertIn('48 layers', app.model_text.get())
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main()
