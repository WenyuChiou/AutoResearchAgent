"""Run ordinary Wiki project selection and reopen behavior with isolated responses."""
from pathlib import Path
import shutil,subprocess,unittest

class ProjectRecoveryTests(unittest.TestCase):
    def test_same_title_project_reopen(self):
        node=shutil.which('node')
        self.assertIsNotNone(node,'Node is required for the Wiki renderer tests')
        result=subprocess.run([node,str(Path(__file__).with_suffix('.cjs'))],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',timeout=30,check=False)
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertIn('PASS same-title labels',result.stdout)
