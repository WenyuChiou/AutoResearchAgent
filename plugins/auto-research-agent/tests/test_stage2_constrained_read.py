"""A Windows read probe must work without relaxing ConstrainedLanguage."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_live.preflight import read_probe_command, _allowed_read_commands


class ConstrainedReadTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows PowerShell execution only")
    def test_read_preserves_nonce_in_constrained_language_and_literal_path(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            self.skipTest("PowerShell unavailable on this Windows host")
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "probe'[1].txt"
            source.write_text("constrained-read-nonce-74fe", encoding="utf-8")
            result = subprocess.run(
                [
                    shell,
                    "-NoProfile",
                    "-Command",
                    "$ExecutionContext.SessionState.LanguageMode = 'ConstrainedLanguage'; "
                    + read_probe_command(str(source)),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "constrained-read-nonce-74fe")

    def test_historical_read_and_cmdlet_are_exact_allowlisted_operations(self):
        allowed = _allowed_read_commands("probe'[1].txt", "windows")
        self.assertIn("[System.IO.File]::ReadAllText('probe''[1].txt')", allowed)
        self.assertNotIn("Write-Output 'fabricated nonce'", allowed)
        self.assertNotIn(read_probe_command("different.txt"), allowed)


if __name__ == "__main__":
    unittest.main()
