"""Prepare a fresh local runtime binding observation, never a message permit."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from harness_chat_binding import load_binding
from harness_chat_runtime import runtime_module_paths

HERE = Path(__file__).resolve().parent
UI = HERE.parents[1]


def observation(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024): digest.update(chunk)
    return {'path': str(path), 'sha256': digest.hexdigest()}


def prepare(output):
    output = Path(output)
    if not output.is_absolute() or output.exists():
        raise ValueError('new-absolute-observation-directory-required')
    if not output.resolve().is_relative_to((UI / 'reports').resolve()):
        raise ValueError('observation-output-must-be-local-report')
    original = UI / 'runtime/v9-harness-chat/operator-chat-config.json'
    raw = original.read_bytes()
    old_pin = hashlib.sha256(raw).hexdigest()
    if (original.parent / 'config.sha256').read_text().strip() != old_pin:
        raise ValueError('original-operator-external-pin-differs')
    old = json.loads(raw)
    modules = runtime_module_paths()
    manifest = {'kind': 'V9ChatRuntimeBinding', 'version': 1,
                'executable': observation(old['executable']), 'config': observation(old['config_path']),
                'modules': {name: observation(path) for name, path in modules.items()}}
    output.mkdir(parents=True)
    descriptor = output / 'runtime-binding.json'
    content = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    descriptor.write_bytes(content)
    pin = hashlib.sha256(content).hexdigest()
    (output / 'runtime-binding.sha256').write_text(pin + '\n', encoding='ascii')
    started = time.monotonic()
    bound = load_binding(descriptor, pin, modules, old['executable'], old['config_path'])
    bound.verify(actual_modules=runtime_module_paths())
    elapsed = time.monotonic() - started
    result = {'kind': 'V9LocalRuntimeBindingObservation', 'manifest_sha256': pin,
              'module_file_count': len(modules), 'full_file_rechecks': 2,
              'verification_wall_seconds': round(elapsed, 3),
              'original_operator_sha256': old_pin, 'message_permit_created': False,
              'authorization': None, 'chat_registered': False, 'send_ready': False,
              'model_messages': 0, 'old_budget_opened': False, 'old_budget_changed': False,
              'source_claim': 'host-owned candidate files plus fixed original native channel and chat asset; not memory attestation'}
    (output / 'preparation.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output)))


if __name__ == '__main__': main()
