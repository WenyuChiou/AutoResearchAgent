"""Host-owned local file closure; manifests do not choose runtime locations."""
from pathlib import Path
import hashlib
import sys

HERE = Path(__file__).resolve().parent
UI = HERE.parents[1]


def retained_bridge_status():
    """Verify retained bridge code without importing it or opening chat state.

    These are source-integrity observations, not native connection evidence.
    The active HTTP host separately reports whether it installed the service.
    """
    pins = {
        'harness_chat.py': '5e03a370d795cf518b6c906b86106cb2bd144fd941ed2eff875887b124b8bdb4',
        'harness_chat_continuation.py': '8c14479d6f7db4e7193002b79b301ce8e154ec1569b174bd0f6f37599204b633',
        'harness_chat_http.py': '91ac8dc14098c9b16193085e9dcf3be099c54abc099b7fb0f3003ffdf30d095f',
        'harness_chat_permit.py': 'a671c5085f16d0fdef57da48361bdabd246e36db790704fe8eeddc7a6c500345',
        'harness_chat_rpc.py': 'e1c8ac3d049f8dd5406d13463800249510914d069f9167bbde4aec8fed117a8f',
        'harness_chat_tools.py': '4426d3d7ce1bd497725dcf840ac9b759ac4ad7f2fa7b4d16e8bc25de97f40a04',
    }
    checked = {}
    for name, expected in pins.items():
        try:
            path = HERE / name
            info = path.lstat()
            checked[name] = (not path.is_symlink()
                and not (getattr(info, 'st_file_attributes', 0) & 0x400)
                and info.st_size <= 1024 * 1024
                and hashlib.sha256(path.read_bytes()).hexdigest() == expected)
        except OSError:
            checked[name] = False
    return dict(kind='RetainedCodexBridgeSourceCheck', files=checked,
                verified=all(checked.values()), native_connection_verified=False,
                protocol_execution_tested=False, scope='source-integrity-only')


def runtime_module_paths():
    result = {}
    for path in sorted(HERE.glob('*.py')):
        if not path.stem.isidentifier() or path.name.startswith('test_'):
            continue
        module = sys.modules.get(path.stem)
        actual = getattr(module, '__file__', None) if module is not None else None
        if actual and Path(actual).resolve() != path.resolve():
            raise ValueError('chat-runtime-loaded-module-path-differs')
        result[path.stem] = str(Path(actual).resolve() if actual else path.resolve())
    # The original process channel is intentionally outside the display candidate.
    expected = UI / 'work/v7-functional-candidate/native_stage1.py'
    module = sys.modules.get('native_stage1')
    actual = getattr(module, '__file__', None) if module is not None else None
    if actual and Path(actual).resolve() != expected.resolve():
        raise ValueError('chat-runtime-native-channel-path-differs')
    result['native_stage1'] = str(expected.resolve())
    # These sources can change client-side gating but never grant authorization.
    result['ui_chat_asset'] = str(HERE / 'v9-harness-chat.js')
    return result
