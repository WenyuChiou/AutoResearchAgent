"""Check the generated module, including V9 composition, with Node's parser."""
import os
from pathlib import Path
import subprocess
import tempfile

from build_v7 import snapshot
from run_v9 import MODULES

HERE = Path(__file__).resolve().parent
repo = Path(os.environ.get('HARNESS_REPO', HERE.parent))
assets, _ = snapshot(repo)
app = assets['/app.js']
at = app.rfind(b'})();')
if at < 0:
    raise ValueError('missing closure')
app = app[:at] + b'\nconst n9TranslationBundle={schema_version:1,packets:[]};\n' + b'\n'.join((HERE/name).read_bytes() for name in MODULES) + b'\n' + app[at:]
with tempfile.TemporaryDirectory() as temporary:
    target = Path(temporary)/'app.mjs'
    target.write_bytes(app)
    subprocess.run([os.environ.get('NODE_BINARY', 'node'), '--check', str(target)], check=True)
print('Generated V9 module syntax passed.')
