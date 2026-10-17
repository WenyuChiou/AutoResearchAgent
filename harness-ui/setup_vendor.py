"""Install only the pinned Three.js bytes; no package scripts or extraction."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--from-file', type=Path, help='Reuse an existing verified three.core.js')
    args = parser.parse_args()
    vendor = Path(__file__).resolve().parent / 'renderer/vendor'
    pin = json.loads((vendor/'three.core.provenance.json').read_text(encoding='utf-8'))
    if args.from_file:
        content = args.from_file.read_bytes()
    else:
        with urlopen(pin['tarball_url'], timeout=30) as response:
            data = response.read(20*1024*1024+1)
        if len(data)>20*1024*1024 or hashlib.sha256(data).hexdigest()!=pin['tarball_sha256']:
            raise ValueError('vendor archive differs from pinned release')
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            member = archive.getmember(pin['archive_member'])
            if not member.isfile() or member.size != pin['archive_member_bytes']:
                raise ValueError('vendor member differs')
            content = archive.extractfile(member).read()
    if hashlib.sha256(content).hexdigest() != pin['archive_member_sha256']:
        raise ValueError('Three.js content hash differs')
    target = vendor/'three.core.js'
    if target.exists() and target.read_bytes()!=content:
        raise ValueError('existing vendor differs; retained without overwriting')
    target.write_bytes(content)
    print('Pinned Three.js ready; no package scripts executed.')


if __name__ == '__main__':
    main()
