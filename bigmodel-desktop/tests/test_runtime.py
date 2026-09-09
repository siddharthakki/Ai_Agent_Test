import unittest
from unittest.mock import patch
from bigmodel.runtime import windows_builds


class RuntimeTests(unittest.TestCase):
    def test_source_only_release_skipped_and_cuda_dependency_paired(self):
        release = [{'assets':[{'name':'nightly-tag.txt'}]}, {'assets':[
            {'name':'llama-b123-bin-win-cuda-12.4-x64.zip'},
            {'name':'cudart-llama-bin-win-cuda-12.4-x64.zip'},
            {'name':'llama-b123-bin-win-cuda-13.3-x64.zip'},
            {'name':'llama-b123-bin-win-cpu-x64.zip'}]}]
        with patch('bigmodel.runtime.request_json', return_value=release):
            result = windows_builds()
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]['dependencies']), 1)
        self.assertTrue(result[0]['dependencies'][0]['name'].startswith('cudart-'))


if __name__ == '__main__':
    unittest.main()
