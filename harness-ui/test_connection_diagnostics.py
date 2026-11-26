"""Run the pure settings presentation contract with no model or Host calls."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ConnectionDiagnosticsTests(unittest.TestCase):
    def test_connection_diagnostics(self):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        result = subprocess.run([node, '--test', str(Path(__file__).with_suffix('.cjs'))],
                                capture_output=True, text=True, encoding='utf8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
